
import asyncio
import json
import websockets


class Rover:
    def __init__(self, ip):
        self.uri = f"ws://{ip}:81"
        self.ws = None

    async def connect(self):
        self.ws = await websockets.connect(self.uri)
        await self.send({"type": "hello"})
        print("Connected to rover")

    async def send(self, command):
        await self.ws.send(json.dumps(command))
        response = await asyncio.wait_for(self.ws.recv(), timeout=5)
        data = json.loads(response)
        print("Rover:", data)
        return data

    async def heartbeat(self):
        while True:
            await self.send({"type": "heartbeat"})
            await asyncio.sleep(1)

    async def status(self):
        return await self.send({"type": "status"})

    async def drive(self, direction, speed=10, duration=250):
        return await self.send({
            "type": "drive",
            "direction": direction,
            "speed_pct": speed,
            "duration_ms": duration
        })

    async def pick(self):
        return await self.send({"type": "pick"})

    async def drop(self):
        return await self.send({"type": "drop"})

    async def stop(self):
        return await self.send({"type": "stop"})

    async def close(self):
        if self.ws:
            await self.ws.close()


async def main():
    rover_ip = input("Enter ESP32-S3 IP address: ").strip()
    rover = Rover(rover_ip)

    try:
        await rover.connect()
        await rover.status()

        while True:
            print("\n1. Forward")
            print("2. Reverse")
            print("3. Left")
            print("4. Right")
            print("5. Stop")
            print("6. Pick")
            print("7. Drop")
            print("8. Status")
            print("0. Exit")

            choice = input("Choose: ").strip()

            if choice == "1":
                await rover.drive("forward")
            elif choice == "2":
                await rover.drive("reverse")
            elif choice == "3":
                await rover.drive("left")
            elif choice == "4":
                await rover.drive("right")
            elif choice == "5":
                await rover.stop()
            elif choice == "6":
                await rover.pick()
            elif choice == "7":
                await rover.drop()
            elif choice == "8":
                await rover.status()
            elif choice == "0":
                await rover.stop()
                break
            else:
                print("Invalid option")

    except (OSError, asyncio.TimeoutError, websockets.WebSocketException) as e:
        print("Connection error:", e)
    finally:
        await rover.close()


if __name__ == "__main__":
    asyncio.run(main())
