#!/usr/bin/env python3
"""
Bluetooth Exchange Test for Reticulum using Bleak

Tests the Bluetooth interface with MAC address F9:7F:43:01:0A:D4

Usage:
  Device A: python3 bluetooth_test_exchange.py --device=A
  Device B: python3 bluetooth_test_exchange.py --device=B

Both devices will attempt to connect to the specified MAC address.
"""

import argparse
import sys
import os
import time
import tempfile
sys.path.insert(0, os.getcwd())
import RNS

# Target MAC address
PEER_MAC = "F9:7F:43:01:0A:D4"

class BluetoothExchangeHandler:
    def __init__(self, device_id):
        self.device_id = device_id
        self.received_announces = []
        self.start_time = time.time()

    def received_announce(self, destination_hash, announced_identity, app_data):
        announce_data = app_data.decode() if app_data else "No data"
        self.received_announces.append({
            "hash": RNS.prettyhexrep(destination_hash),
            "data": announce_data,
            "time": time.time(),
            "elapsed": time.time() - self.start_time
        })

        print(f"🔵 RECEIVED ANNOUNCE from peer:")
        print(f"   Hash: {RNS.prettyhexrep(destination_hash)}")
        print(f"   Data: {announce_data}")
        print(f"   Time: +{time.time() - self.start_time:.1f}s")
        print(f"   Total received: {len(self.received_announces)}")

def create_config(device_id):
    """Create test configuration for Bluetooth interface"""
    config_content = f"""[reticulum]
  enable_transport = yes
  share_instance = no
  instance_name = bluetooth_exchange_{device_id}
  panic_on_interface_error = no

[logging]
  loglevel = 3

[interfaces]
  [[Bluetooth Exchange Interface]]
    type = BluetoothInterface
    enabled = yes
    peer_address = {PEER_MAC}
    connection_interval = 3.0
"""
    return config_content

def main():
    parser = argparse.ArgumentParser(description="Bluetooth exchange test")
    parser.add_argument("--device", choices=["A", "B"], required=True,
                       help="Device identifier (A or B)")

    args = parser.parse_args()

    print(f"🔵 Bluetooth Exchange Test - Device {args.device}")
    print(f"🎯 Target MAC: {PEER_MAC}")
    print("=" * 50)

    # Check Bleak availability
    try:
        import bleak
        print(f"✅ Bleak library available")
    except ImportError:
        print("❌ Bleak not available. Install with: pip install bleak")
        return 1

    # Create test config directory
    config_dir = f"bluetooth_exchange_{args.device}_config"
    os.makedirs(config_dir, exist_ok=True)

    config_content = create_config(args.device)
    config_path = os.path.join(config_dir, "config")
    with open(config_path, "w") as f:
        f.write(config_content)

    print(f"📁 Created config: {config_dir}/config")
    print(f"🔌 Connecting to peer: {PEER_MAC}")

    try:
        # Initialize Reticulum
        print("🔧 Initializing Reticulum...")
        reticulum = RNS.Reticulum(config_dir)
        print(f"✅ Reticulum initialized")

        # Create identity and destination
        identity = RNS.Identity()
        destination = RNS.Destination(
            identity,
            RNS.Destination.IN,
            RNS.Destination.SINGLE,
            "bluetooth_exchange",
            args.device
        )

        print(f"📍 Device {args.device} destination: {RNS.prettyhexrep(destination.hash)}")

        # Set up announce handler
        handler = BluetoothExchangeHandler(args.device)
        RNS.Transport.register_announce_handler(handler)

        # Initial announce
        node_info = f"Device-{args.device}-{int(time.time()) % 10000}"
        destination.announce(app_data=node_info.encode("utf-8"))
        print(f"📡 Initial announce sent: {node_info}")

        # Test loop
        announce_count = 1
        last_announce = time.time()
        start_time = time.time()

        print(f"\n🚀 Running exchange test...")
        print(f"   📢 Will announce every 10 seconds")
        print(f"   👂 Listening for peer Device {'B' if args.device == 'A' else 'A'}")
        print(f"   🔌 BLE connection attempts every 3 seconds")
        print(f"   ⏰ Press Ctrl+C to stop")
        print()

        while True:
            time.sleep(1)
            elapsed = time.time() - start_time

            # Announce every 10 seconds
            if time.time() - last_announce >= 10:
                node_info = f"Device-{args.device}-{int(time.time()) % 10000}"
                destination.announce(app_data=node_info.encode("utf-8"))
                announce_count += 1
                last_announce = time.time()
                print(f"📡 Announce #{announce_count}: {node_info} (+{elapsed:.1f}s)")

            # Show status every 20 seconds
            if int(elapsed) % 20 == 0 and int(elapsed) > 0:
                print(f"\n📊 Status at +{elapsed:.0f}s:")
                print(f"   📢 Announces sent: {announce_count}")
                print(f"   👂 Announces received: {len(handler.received_announces)}")

                if handler.received_announces:
                    print(f"   ✅ COMMUNICATION WORKING!")
                    last_received = handler.received_announces[-1]
                    print(f"   📥 Last received: {last_received['data']} (+{last_received['elapsed']:.1f}s)")
                else:
                    print(f"   ⏳ Waiting for peer connection...")
                    print(f"   💡 Check that peer device is running and within BLE range")

                print()
                time.sleep(1)  # Prevent multiple status prints

    except KeyboardInterrupt:
        print(f"\n🛑 Test stopped by user")
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # Final results
    elapsed = time.time() - start_time
    print(f"\n📊 Final Results (after {elapsed:.1f}s):")
    print(f"   📢 Total announces sent: {announce_count}")
    print(f"   👂 Total announces received: {len(handler.received_announces)}")

    if handler.received_announces:
        print(f"\n✅ SUCCESS: Bluetooth exchange working!")
        print(f"   📈 Communication timeline:")
        for i, announce in enumerate(handler.received_announces, 1):
            print(f"     {i}. {announce['data']} at +{announce['elapsed']:.1f}s")

        # Calculate average delay
        if len(handler.received_announces) > 1:
            intervals = []
            for i in range(1, len(handler.received_announces)):
                interval = handler.received_announces[i]['elapsed'] - handler.received_announces[i-1]['elapsed']
                intervals.append(interval)
            avg_interval = sum(intervals) / len(intervals)
            print(f"   ⏱️  Average receive interval: {avg_interval:.1f}s")

    else:
        print(f"\n⚠️  No communication established")
        print(f"   🔍 Troubleshooting checklist:")
        print(f"     1. Both devices running this test?")
        print(f"     2. Devices within BLE range (~10-30m)?")
        print(f"     3. Bluetooth enabled on both devices?")
        print(f"     4. MAC address {PEER_MAC} correct?")
        print(f"     5. Check Reticulum logs for connection errors")

    return 0

if __name__ == "__main__":
    sys.exit(main())