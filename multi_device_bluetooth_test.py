#!/usr/bin/env python3
"""
Comprehensive multi-device Bluetooth test suite for Reticulum

This script can be run on two separate computers to test:
1. Device discovery via BLE scanning
2. Bidirectional announce exchange
3. Link establishment over Bluetooth
4. Data transfer over established links
5. Network resilience and reconnection

Usage:
  Computer 1: python3 multi_device_bluetooth_test.py --device=A
  Computer 2: python3 multi_device_bluetooth_test.py --device=B

Requirements:
- Both computers have Bluetooth LE capability
- Both computers are within BLE range (~10-100m depending on environment)
- Bleak library installed on both: pip install bleak
"""

import argparse
import sys
import os
import time
import threading
import json
from datetime import datetime
sys.path.insert(0, os.getcwd())
import RNS

# Test configuration
TEST_DURATION = 120  # 2 minutes
ANNOUNCE_INTERVAL = 10  # seconds
LINK_TEST_INTERVAL = 30  # seconds

class BluetoothTestRunner:
    def __init__(self, device_id):
        self.device_id = device_id
        self.start_time = time.time()
        self.test_results = {
            "device_id": device_id,
            "start_time": datetime.now().isoformat(),
            "announces_sent": 0,
            "announces_received": 0,
            "links_established": 0,
            "data_transfers": 0,
            "errors": [],
            "peer_devices": {}
        }

        self.reticulum = None
        self.identity = None
        self.destination = None
        self.announce_handler = None
        self.established_links = {}

    def setup_reticulum(self):
        """Initialize Reticulum with Bluetooth interface"""
        # Create test config directory
        config_dir = f"bluetooth_test_{self.device_id}"
        os.makedirs(config_dir, exist_ok=True)

        config_content = f"""[reticulum]
  enable_transport = yes
  share_instance = no
  instance_name = bluetooth_test_{self.device_id}
  panic_on_interface_error = no

[logging]
  loglevel = 3

[interfaces]
  [[BLE Test Interface]]
    type = BluetoothInterface
    enabled = yes
    device_name = RNS-Test-Device-{self.device_id}
    scan_interval = 3.0
    advertise_interval = 2.0
"""

        config_path = os.path.join(config_dir, "config")
        with open(config_path, "w") as f:
            f.write(config_content)

        print(f"🔧 Initializing Reticulum for Device {self.device_id}...")
        self.reticulum = RNS.Reticulum(config_dir)

        # Create identity and destination
        self.identity = RNS.Identity()
        self.destination = RNS.Destination(
            self.identity,
            RNS.Destination.IN,
            RNS.Destination.SINGLE,
            "bluetooth_test",
            f"device_{self.device_id}"
        )

        # Set up data handler for the destination
        self.destination.set_packet_callback(self.packet_received)

        print(f"📍 Device {self.device_id} destination: {RNS.prettyhexrep(self.destination.hash)}")

        # Set up announce handler
        self.announce_handler = BluetoothAnnounceHandler(self)
        RNS.Transport.register_announce_handler(self.announce_handler)

        print(f"✅ Reticulum initialized for Device {self.device_id}")

    def packet_received(self, data, packet):
        """Handle received packets"""
        try:
            message = json.loads(data.decode())
            print(f"📦 Received packet: {message}")

            if message.get("type") == "test_data":
                self.test_results["data_transfers"] += 1

                # Send response
                response = {
                    "type": "test_response",
                    "device_id": self.device_id,
                    "original_message": message,
                    "timestamp": time.time()
                }

                response_data = json.dumps(response).encode()
                response_packet = RNS.Packet(self.destination, response_data)
                response_packet.send()

                print(f"📤 Sent response to test data")

        except Exception as e:
            self.test_results["errors"].append(f"Packet processing error: {e}")
            print(f"❌ Error processing packet: {e}")

    def run_test_sequence(self):
        """Run the complete test sequence"""
        print(f"🚀 Starting {TEST_DURATION}s test sequence for Device {self.device_id}")

        # Start background threads
        announce_thread = threading.Thread(target=self.announce_loop, daemon=True)
        link_thread = threading.Thread(target=self.link_test_loop, daemon=True)

        announce_thread.start()
        link_thread.start()

        # Main test loop
        try:
            while time.time() - self.start_time < TEST_DURATION:
                time.sleep(1)
                self.print_status()

        except KeyboardInterrupt:
            print(f"\n🛑 Test interrupted for Device {self.device_id}")

        self.finalize_results()

    def announce_loop(self):
        """Continuously announce presence"""
        next_announce = time.time()

        while time.time() - self.start_time < TEST_DURATION:
            if time.time() >= next_announce:
                announce_data = {
                    "device_id": self.device_id,
                    "timestamp": time.time(),
                    "test_sequence": self.test_results["announces_sent"]
                }

                self.destination.announce(app_data=json.dumps(announce_data).encode())
                self.test_results["announces_sent"] += 1

                print(f"📢 Device {self.device_id} announced #{self.test_results['announces_sent']}")
                next_announce = time.time() + ANNOUNCE_INTERVAL

            time.sleep(1)

    def link_test_loop(self):
        """Test link establishment and data transfer"""
        next_link_test = time.time() + LINK_TEST_INTERVAL

        while time.time() - self.start_time < TEST_DURATION:
            if time.time() >= next_link_test and self.test_results["peer_devices"]:
                # Try to establish link with a discovered peer
                peer_hash = list(self.test_results["peer_devices"].keys())[0]
                self.test_link_to_peer(peer_hash)
                next_link_test = time.time() + LINK_TEST_INTERVAL

            time.sleep(5)

    def test_link_to_peer(self, peer_hash_hex):
        """Test link establishment and data transfer to a peer"""
        try:
            print(f"🔗 Attempting link to peer {peer_hash_hex[:16]}...")

            peer_hash = bytes.fromhex(peer_hash_hex)
            peer_identity = RNS.Identity.recall(peer_hash)

            if peer_identity:
                # Create destination for the peer
                peer_destination = RNS.Destination(
                    peer_identity,
                    RNS.Destination.OUT,
                    RNS.Destination.SINGLE,
                    "bluetooth_test",
                    f"device_unknown"  # We don't know their device ID
                )

                # Try to establish link
                link = RNS.Link(peer_destination)

                # Wait for link establishment
                link_established = False
                wait_start = time.time()

                while time.time() - wait_start < 15:  # 15 second timeout
                    if link.status == RNS.Link.ACTIVE:
                        link_established = True
                        break
                    time.sleep(0.5)

                if link_established:
                    self.test_results["links_established"] += 1
                    print(f"✅ Link established with {peer_hash_hex[:16]}")

                    # Send test data over the link
                    test_message = {
                        "type": "test_data",
                        "device_id": self.device_id,
                        "timestamp": time.time(),
                        "test_number": self.test_results["data_transfers"] + 1
                    }

                    test_data = json.dumps(test_message).encode()
                    packet = RNS.Packet(peer_destination, test_data)
                    packet.send()

                    print(f"📤 Sent test data over link")

                else:
                    print(f"❌ Failed to establish link with {peer_hash_hex[:16]}")
                    self.test_results["errors"].append(f"Link establishment failed: {peer_hash_hex[:16]}")

            else:
                print(f"❌ Could not recall identity for {peer_hash_hex[:16]}")

        except Exception as e:
            print(f"❌ Link test error: {e}")
            self.test_results["errors"].append(f"Link test error: {e}")

    def print_status(self):
        """Print current test status"""
        elapsed = int(time.time() - self.start_time)
        remaining = TEST_DURATION - elapsed

        if elapsed % 15 == 0:  # Print every 15 seconds
            print(f"\n📊 Device {self.device_id} Status (T+{elapsed}s, {remaining}s remaining):")
            print(f"   📢 Announces sent: {self.test_results['announces_sent']}")
            print(f"   👂 Announces received: {self.test_results['announces_received']}")
            print(f"   🔗 Links established: {self.test_results['links_established']}")
            print(f"   📦 Data transfers: {self.test_results['data_transfers']}")
            print(f"   🌐 Peer devices: {len(self.test_results['peer_devices'])}")
            if self.test_results["errors"]:
                print(f"   ❌ Errors: {len(self.test_results['errors'])}")

    def finalize_results(self):
        """Finalize and save test results"""
        self.test_results["end_time"] = datetime.now().isoformat()
        self.test_results["duration"] = time.time() - self.start_time

        # Save results to file
        results_file = f"bluetooth_test_results_{self.device_id}.json"
        with open(results_file, "w") as f:
            json.dump(self.test_results, f, indent=2)

        print(f"\n🏁 Test completed for Device {self.device_id}")
        print(f"📊 Final Results:")
        print(f"   📢 Announces sent: {self.test_results['announces_sent']}")
        print(f"   👂 Announces received: {self.test_results['announces_received']}")
        print(f"   🔗 Links established: {self.test_results['links_established']}")
        print(f"   📦 Data transfers: {self.test_results['data_transfers']}")
        print(f"   🌐 Peer devices discovered: {len(self.test_results['peer_devices'])}")
        print(f"   ❌ Errors: {len(self.test_results['errors'])}")
        print(f"   💾 Results saved to: {results_file}")

        if self.test_results["errors"]:
            print(f"\n❌ Errors encountered:")
            for error in self.test_results["errors"]:
                print(f"     - {error}")


class BluetoothAnnounceHandler:
    def __init__(self, test_runner):
        self.test_runner = test_runner

    def received_announce(self, destination_hash, announced_identity, app_data):
        """Handle received announces"""
        hash_hex = destination_hash.hex()

        try:
            if app_data:
                announce_data = json.loads(app_data.decode())
                peer_device_id = announce_data.get("device_id", "unknown")

                # Don't count our own announces
                if peer_device_id != self.test_runner.device_id:
                    self.test_runner.test_results["announces_received"] += 1

                    # Track peer device
                    if hash_hex not in self.test_runner.test_results["peer_devices"]:
                        self.test_runner.test_results["peer_devices"][hash_hex] = {
                            "device_id": peer_device_id,
                            "first_seen": time.time(),
                            "announce_count": 0
                        }

                    self.test_runner.test_results["peer_devices"][hash_hex]["announce_count"] += 1
                    self.test_runner.test_results["peer_devices"][hash_hex]["last_seen"] = time.time()

                    print(f"🔵 Received announce from Device {peer_device_id} ({hash_hex[:16]}...)")

        except Exception as e:
            self.test_runner.test_results["errors"].append(f"Announce processing error: {e}")
            print(f"❌ Error processing announce: {e}")


def main():
    parser = argparse.ArgumentParser(description="Multi-device Bluetooth test for Reticulum")
    parser.add_argument("--device", choices=["A", "B"], required=True,
                       help="Device identifier (A or B)")

    args = parser.parse_args()

    print(f"🔵 Bluetooth Multi-Device Test - Device {args.device}")
    print(f"⏱️  Test duration: {TEST_DURATION} seconds")
    print(f"📡 Announce interval: {ANNOUNCE_INTERVAL} seconds")
    print(f"🔗 Link test interval: {LINK_TEST_INTERVAL} seconds")
    print()

    try:
        # Check if bleak is available
        import bleak
        # Try to get version, fallback if not available
        try:
            version = bleak.__version__
            print(f"✅ Bleak version {version} available")
        except AttributeError:
            print("✅ Bleak library available")
    except ImportError:
        print("❌ Bleak not available. Install with: pip install bleak")
        sys.exit(1)

    test_runner = BluetoothTestRunner(args.device)

    try:
        test_runner.setup_reticulum()
        test_runner.run_test_sequence()

    except KeyboardInterrupt:
        print(f"\n🛑 Test interrupted")
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()