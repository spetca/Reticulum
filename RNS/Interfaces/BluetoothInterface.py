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
    BITRATE_GUESS = 50000
    DEFAULT_IFAC_SIZE = 8

    # BLE constants
    BLE_MAX_PAYLOAD = 27  # Conservative BLE advertisement data size
    RETICULUM_SERVICE_UUID = "6ba7b810-9dad-11d1-80b4-00c04fd430c8"
    RETICULUM_CHAR_UUID = "6ba7b811-9dad-11d1-80b4-00c04fd430c8"

    def __init__(self, owner, configuration):
        try:
            import bleak
        except ImportError:
            RNS.log("Bluetooth interface requires Bleak: pip install bleak", RNS.LOG_CRITICAL)
            RNS.panic()

        super().__init__()

        c = Interface.get_config_obj(configuration)
        self.name = c["name"]
        self.device_name = c.get("device_name", f"RNS-{self.name}")
        self.scan_interval = float(c.get("scan_interval", 5.0))
        self.advertise_interval = float(c.get("advertise_interval", 2.0))

        # Conservative MTU for BLE
        self.HW_MTU = self.BLE_MAX_PAYLOAD - 4  # Reserve bytes for framing

        self.owner = owner
        self.online = False
        self.bitrate = self.BITRATE_GUESS
        self.bleak = bleak

        # Packet handling
        self.rx_fragments = {}
        self.tx_queue = []
        self.last_packet_ids = set()

        # BLE components
        self.scanner = None
        self.advertiser = None
        self.current_advertisement_data = None

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
            self.loop.run_until_complete(self._async_main())
        except Exception as e:
            RNS.log(f"Async loop error: {e}", RNS.LOG_ERROR)
        finally:
            self.loop.close()

    async def _async_main(self):
        """Main async function that runs scanning and advertising"""
        # Start scanning and advertising concurrently
        await asyncio.gather(
            self._scan_loop(),
            self._advertise_loop(),
            return_exceptions=True
        )

    async def _scan_loop(self):
        """Continuously scan for BLE devices with Reticulum service"""
        while self.online:
            try:
                RNS.log("Scanning for BLE devices...", RNS.LOG_EXTREME)

                # Scan for devices
                scanner = self.bleak.BleakScanner()
                devices = await scanner.discover(timeout=self.scan_interval)

                for device in devices:
                    if device.name and "RNS-" in device.name:
                        RNS.log(f"Found Reticulum BLE device: {device.name} ({device.address})", RNS.LOG_DEBUG)

                        # Try to connect and exchange data
                        await self._attempt_connection(device)

            except Exception as e:
                RNS.log(f"BLE scan error: {e}", RNS.LOG_DEBUG)

            await asyncio.sleep(1)

    async def _attempt_connection(self, device):
        """Attempt to connect to a BLE device and exchange data"""
        try:
            async with self.bleak.BleakClient(device.address) as client:
                # Check if device has our service
                services = await client.get_services()

                reticulum_service = None
                for service in services:
                    if service.uuid.lower() == self.RETICULUM_SERVICE_UUID.lower():
                        reticulum_service = service
                        break

                if not reticulum_service:
                    return

                # Find our characteristic
                char = None
                for characteristic in reticulum_service.characteristics:
                    if characteristic.uuid.lower() == self.RETICULUM_CHAR_UUID.lower():
                        char = characteristic
                        break

                if not char:
                    return

                # Try to read data
                if "read" in char.properties:
                    data = await client.read_gatt_char(char.uuid)
                    if data and len(data) > 0:
                        self.process_bluetooth_data(data, device.address)

                # Try to write queued data
                if "write" in char.properties and self.tx_queue:
                    packet_data = self.tx_queue.pop(0)
                    packet_id, fragments = self.fragment_packet(packet_data)

                    for fragment_num, fragment_data in enumerate(fragments):
                        frame = bytes([packet_id, fragment_num, len(fragments)]) + fragment_data
                        await client.write_gatt_char(char.uuid, frame)
                        await asyncio.sleep(0.1)  # Small delay between writes

        except Exception as e:
            RNS.log(f"BLE connection error with {device.address}: {e}", RNS.LOG_EXTREME)

    async def _advertise_loop(self):
        """Advertise our presence and any queued data"""
        while self.online:
            try:
                # For now, just advertise our presence with device name
                # Real BLE advertising would require platform-specific code
                RNS.log(f"Advertising as {self.device_name}", RNS.LOG_EXTREME)

                # TODO: Implement actual BLE GATT server
                # This would require more complex platform-specific code
                # For demonstration, we'll use a simplified approach

            except Exception as e:
                RNS.log(f"BLE advertising error: {e}", RNS.LOG_DEBUG)

            await asyncio.sleep(self.advertise_interval)

    def packet_processing_loop(self):
        """Process outgoing packets in a separate thread"""
        while self.online:
            if self.tx_queue:
                # Packets will be processed when we connect to other devices
                # in the _attempt_connection method
                pass
            time.sleep(0.1)

    def process_bluetooth_data(self, data, source_addr):
        """Process received Bluetooth data"""
        try:
            # Skip handshake messages
            if data.startswith(b"RNS:"):
                return

            # Simple framing: [packet_id][fragment_num][total_fragments][data]
            if len(data) < 4:
                return

            packet_id = data[0]
            fragment_num = data[1]
            total_fragments = data[2]
            fragment_data = data[3:]

            # Avoid processing duplicate packets
            if packet_id in self.last_packet_ids:
                return

            # Handle single fragment packets
            if total_fragments == 1:
                self.last_packet_ids.add(packet_id)
                if len(self.last_packet_ids) > 100:  # Prevent memory growth
                    self.last_packet_ids.clear()
                self.process_incoming(fragment_data)
                return

            # Handle multi-fragment packets
            if packet_id not in self.rx_fragments:
                self.rx_fragments[packet_id] = {}

            self.rx_fragments[packet_id][fragment_num] = fragment_data

            # Check if we have all fragments
            if len(self.rx_fragments[packet_id]) == total_fragments:
                # Reassemble packet
                full_packet = b""
                for i in range(total_fragments):
                    if i in self.rx_fragments[packet_id]:
                        full_packet += self.rx_fragments[packet_id][i]

                # Clean up and process
                del self.rx_fragments[packet_id]
                self.last_packet_ids.add(packet_id)
                if len(self.last_packet_ids) > 100:
                    self.last_packet_ids.clear()
                self.process_incoming(full_packet)

        except Exception as e:
            RNS.log(f"Bluetooth data processing error: {e}", RNS.LOG_DEBUG)

    def fragment_packet(self, data):
        """Fragment large packets for BLE transmission"""
        max_fragment_size = self.HW_MTU
        fragments = []

        # Use hash of data + timestamp for packet ID to avoid collisions
        packet_id = hash((data, time.time())) % 256

        for i in range(0, len(data), max_fragment_size):
            fragment_data = data[i:i + max_fragment_size]
            fragments.append(fragment_data)

        return packet_id, fragments

    def process_incoming(self, data):
        RNS.log(f"Received {len(data)} bytes via Bluetooth", RNS.LOG_EXTREME)
        self.rxb += len(data)
        self.owner.inbound(data, self)

    def process_outgoing(self, data):
        if self.online:
            RNS.log(f"Queueing {len(data)} bytes for Bluetooth transmission", RNS.LOG_EXTREME)
            self.tx_queue.append(data)

    def detach(self):
        self.online = False
        RNS.log(f"Detaching Bluetooth interface {self}", RNS.LOG_DEBUG)

    def should_ingress_limit(self):
        return False

    def __str__(self):
        return f"BluetoothInterface[{self.name}]"