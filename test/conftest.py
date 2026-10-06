import asyncio
import platform

# Allow the loop to close cleanly on Windows.
if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
