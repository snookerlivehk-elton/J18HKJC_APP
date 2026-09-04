import asyncio
import logging
from etl_pipeline import J18ETLPipeline

logging.basicConfig(level=logging.DEBUG)

async def run():
    p = J18ETLPipeline()
    try:
        res = await p.process_and_load("2026-07-15", 1)
        print("Done", res)
    except Exception as e:
        print("Exception:", e)

asyncio.run(run())