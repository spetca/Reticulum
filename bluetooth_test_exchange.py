#!/usr/bin/env python3
"""
Fixed Bluetooth Exchange Test for Reticulum using Bleak

One device acts as server (the one with MAC F9:7F:43:01:0A:D4)
Other device acts as client (connects to F9:7F:43:01:0A:D4)

Usage:
  Device with MAC F9:7F:43:01:0A:D4: python3 bluetooth_test_exchange_fixed.py --mode=server
  Other device: python3 bluetooth_test_exchange_fixed.py --mode=client
"""

import argparse
import sys
import os
import time
sys.path.insert(0, os.getcwd())
import RNS

# The MAC address of the server device
SERVER_MAC = "F9:7F:43:01:0A:D4"

class BluetoothExchangeHandler:
    def __init__(self, device_mode):
        self.device_mode = device_mode
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

def create_server_config():
    """Create config for server (doesn't need peer_address)"""
    config_content = f"""[reticulum]
  enable_transport = yes
  share_instance = no
  instance_name = bluetooth_server
  panic_on_interface_error = no

[logging]
  loglevel = 3

[interfaces]
  # Server mode - waits for clients to connect
  # Note: This is simplified - real BLE server would need GATT setup
  # For now, we'll use a local interface for the server
  [[Local Interface]]
    type = AutoInterface
    enabled = yes
    devices = lo
"""
    return config_content

def create_client_config():
    """Create config for client (connects to server MAC)"""
    config_content = f"""[reticulum]
  enable_transport = yes
  share_instance = no
  instance_name = bluetooth_client
  panic_on_interface_error = no

[logging]
  loglevel = 3

[interfaces]
  # Client mode - connects to server MAC
  [[Bluetooth Client Interface]]
    type = BluetoothInterface
    enabled = yes
    peer_address = {SERVER_MAC}
    connection_interval = 5.0
"""
    return config_content

def main():
    parser = argparse.ArgumentParser(description="Fixed Bluetooth exchange test")
    parser.add_argument("--mode", choices=["server", "client"], required=True,
                       help="server (device with MAC F9:7F:43:01:0A:D4) or client (other device)")

    args = parser.parse_args()

    print(f"🔵 Bluetooth Exchange Test - {args.mode.upper()} Mode")
    if args.mode == "server":
        print(f"🎧 This device should have MAC: {SERVER_MAC}")
        print(f"   Waiting for client to connect...")
    else:
        print(f"📞 Connecting to server MAC: {SERVER_MAC}")
    print("=" * 50)

    # Check Bleak availability for client
    if args.mode == "client":
        try:
            import bleak
            print(f"✅ Bleak library available")
        except ImportError:
            print("❌ Bleak not available. Install with: pip install bleak")
            return 1

    # Create test config directory
    config_dir = f"bluetooth_{args.mode}_config"
    os.makedirs(config_dir, exist_ok=True)

    if args.mode == "server":
        config_content = create_server_config()
    else:
        config_content = create_client_config()

    config_path = os.path.join(config_dir, "config")
    with open(config_path, "w") as f:
        f.write(config_content)

    print(f"📁 Created config: {config_dir}/config")

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
            args.mode
        )

        print(f"📍 {args.mode.capitalize()} destination: {RNS.prettyhexrep(destination.hash)}")

        # Set up announce handler
        handler = BluetoothExchangeHandler(args.mode)
        RNS.Transport.register_announce_handler(handler)

        # Initial announce
        node_info = f"{args.mode.capitalize()}-{int(time.time()) % 10000}"
        destination.announce(app_data=node_info.encode("utf-8"))
        print(f"📡 Initial announce sent: {node_info}")

        # Test loop
        announce_count = 1
        last_announce = time.time()
        start_time = time.time()

        print(f"\n🚀 Running exchange test...")
        if args.mode == "server":
            print(f"   🎧 Server waiting for client connections")
            print(f"   📡 Announcing every 15 seconds")
        else:
            print(f"   📞 Client attempting BLE connection to {SERVER_MAC}")
            print(f"   📡 Announcing every 10 seconds")
        print(f"   👂 Listening for peer announces")
        print(f"   ⏰ Press Ctrl+C to stop")
        print()

        announce_interval = 15 if args.mode == "server" else 10

        while True:
            time.sleep(1)
            elapsed = time.time() - start_time

            # Announce at different intervals
            if time.time() - last_announce >= announce_interval:
                node_info = f"{args.mode.capitalize()}-{int(time.time()) % 10000}"
                destination.announce(app_data=node_info.encode("utf-8"))
                announce_count += 1
                last_announce = time.time()
                print(f"📡 Announce #{announce_count}: {node_info} (+{elapsed:.1f}s)")

            # Show status every 30 seconds
            if int(elapsed) % 30 == 0 and int(elapsed) > 0:
                print(f"\n📊 Status at +{elapsed:.0f}s:")
                print(f"   📢 Announces sent: {announce_count}")
                print(f"   👂 Announces received: {len(handler.received_announces)}")

                if handler.received_announces:
                    print(f"   ✅ COMMUNICATION WORKING!")
                    last_received = handler.received_announces[-1]
                    print(f"   📥 Last received: {last_received['data']} (+{last_received['elapsed']:.1f}s)")
                else:
                    if args.mode == "server":
                        print(f"   ⏳ Waiting for client to connect...")
                        print(f"   💡 Make sure client device is running and within range")
                    else:
                        print(f"   ⏳ Trying to connect to server...")
                        print(f"   💡 Check that server device is running and MAC is correct")

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
    else:
        print(f"\n⚠️  No communication established")
        if args.mode == "server":
            print(f"   🔍 Server troubleshooting:")
            print(f"     1. Is client device running?")
            print(f"     2. Is this device's MAC actually {SERVER_MAC}?")
            print(f"     3. Check Bluetooth is enabled and visible")
        else:
            print(f"   🔍 Client troubleshooting:")
            print(f"     1. Is server device running?")
            print(f"     2. Is server MAC {SERVER_MAC} correct?")
            print(f"     3. Are devices within BLE range?")
            print(f"     4. Check Bluetooth is enabled")

    return 0

if __name__ == "__main__":
    sys.exit(main())