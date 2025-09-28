# Reticulum License
#
# Copyright (c) 2016-2025 Mark Qvist
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# - The Software shall not be used in any kind of system which includes amongst
#   its functions the ability to purposefully do harm to human beings.
#
# - The Software shall not be used, directly or indirectly, in the creation of
#   an artificial intelligence, machine learning or language model training
#   dataset, including but not limited to any use that contributes to the
#   training or development of such a model or algorithm.
#
# - The above copyright notice and this permission notice shall be included in
#   all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

from RNS.Interfaces.Interface import Interface
import asyncio
import threading
import time
import struct
import RNS

class BluetoothInterface(Interface):
    """
    Bluetooth interface using Bleak for pre-established BLE connections.

    This interface assumes devices are already paired/bonded through the OS
    and uses known MAC addresses to establish direct BLE connections.

    Configuration:
    - peer_address: MAC address of peer device (required)
    - connection_interval: How often to check/maintain connection (default: 5.0)
    """

    BITRATE_GUESS = 50000  # 50 kbps for BLE
    DEFAULT_IFAC_SIZE = 8
    BLE_MTU = 512  # Conservative BLE MTU

    def __init__(self, owner, configuration):
        try:
            import bleak
        except ImportError:
            RNS.log("Bluetooth interface requires Bleak: pip install bleak", RNS.LOG_CRITICAL)
            RNS.panic()

        super().__init__()

        c = Interface.get_config_obj(configuration)
        self.name = c["name"]
        self.peer_address = c.get("peer_address", None)  # MAC address of peer device
        self.connection_interval = float(c.get("connection_interval", 5.0))

        if not self.peer_address:
            raise ValueError("peer_address must be specified for Bluetooth interface")

        self.HW_MTU = self.BLE_MTU
        self.owner = owner
        self.online = False
        self.bitrate = self.BITRATE_GUESS
        self.bleak = bleak

        # Connection management
        self.client = None
        self.connected = False
        self.connection_lock = threading.Lock()

        # Packet handling
        self.tx_queue = []

        # Event loop management
        self.loop = None
        self.loop_thread = None

        try:
            self.start_bluetooth_service()
        except Exception as e:
            RNS.log(f"Could not start Bluetooth interface {self}: {e}", RNS.LOG_ERROR)
            raise e

    def start_bluetooth_service(self):
        RNS.log(f"Starting Bluetooth interface {self}...", RNS.LOG_VERBOSE)

        # Start async event loop in separate thread
        self.loop_thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self.loop_thread.start()

        # Start packet processing thread
        threading.Thread(target=self.packet_processing_loop, daemon=True).start()

        # Wait a moment for initialization
        time.sleep(1)

        self.online = True
        RNS.log(f"Bluetooth interface {self} started", RNS.LOG_VERBOSE)

    def _run_async_loop(self):
        """Run the asyncio event loop in a separate thread"""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        try:
            self.loop.run_until_complete(self._connection_loop())
        except Exception as e:
            RNS.log(f"Async loop error: {e}", RNS.LOG_ERROR)
        finally:
            self.loop.close()

    async def _connection_loop(self):
        """Main connection management loop"""
        while self.online:
            try:
                if not self.connected:
                    await self._establish_connection()
                else:
                    # Check connection health
                    await asyncio.sleep(self.connection_interval)

            except Exception as e:
                RNS.log(f"Connection loop error: {e}", RNS.LOG_DEBUG)
                self.connected = False
                await asyncio.sleep(2)

    async def _establish_connection(self):
        """Establish BLE connection to peer device"""
        try:
            RNS.log(f"Connecting to BLE device {self.peer_address}...", RNS.LOG_DEBUG)

            # Create BLE client
            self.client = self.bleak.BleakClient(self.peer_address)

            # Connect to the device
            await self.client.connect()

            with self.connection_lock:
                self.connected = True

            RNS.log(f"Connected to BLE device {self.peer_address}", RNS.LOG_VERBOSE)

            # Start communication
            await self._handle_communication()

        except Exception as e:
            RNS.log(f"Failed to connect to {self.peer_address}: {e}", RNS.LOG_DEBUG)
            self.connected = False
            if self.client:
                try:
                    await self.client.disconnect()
                except:
                    pass

    async def _handle_communication(self):
        """Handle communication over established BLE connection"""
        # This is simplified - in a real implementation you'd use BLE characteristics
        # For now, we'll use a simple approach where we periodically check for data

        while self.connected and self.online:
            try:
                # Process outgoing queue
                if self.tx_queue:
                    with self.connection_lock:
                        if self.tx_queue:
                            data = self.tx_queue.pop(0)
                            # In a real BLE implementation, you'd write to a characteristic
                            # For demonstration, we'll just log it
                            RNS.log(f"Would send {len(data)} bytes via BLE", RNS.LOG_EXTREME)
                            self.txb += len(data)

                await asyncio.sleep(0.1)

            except Exception as e:
                RNS.log(f"Communication error: {e}", RNS.LOG_ERROR)
                self.connected = False
                break

        # Disconnect when done
        if self.client and self.client.is_connected:
            try:
                await self.client.disconnect()
            except:
                pass

    def packet_processing_loop(self):
        """Process packets in a separate thread"""
        while self.online:
            # This thread handles any synchronous packet processing
            time.sleep(0.1)

    def process_incoming(self, data):
        """Process incoming data"""
        RNS.log(f"Received {len(data)} bytes via Bluetooth", RNS.LOG_EXTREME)
        self.rxb += len(data)
        self.owner.inbound(data, self)

    def process_outgoing(self, data):
        """Queue data for transmission"""
        if self.online:
            RNS.log(f"Queueing {len(data)} bytes for Bluetooth transmission", RNS.LOG_EXTREME)
            self.tx_queue.append(data)

    def detach(self):
        """Detach the interface"""
        self.online = False
        self.connected = False

        # Disconnect if connected
        if self.client and hasattr(self.client, 'is_connected') and self.client.is_connected:
            # We can't call async methods from sync context easily,
            # so we'll just mark as disconnected and let the async loop handle cleanup
            pass

        RNS.log(f"Detached Bluetooth interface {self}", RNS.LOG_DEBUG)

    def should_ingress_limit(self):
        return False

    def __str__(self):
        return f"BluetoothInterface[{self.name} -> {self.peer_address}]"