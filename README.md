# aiometrics
Generate metrics from asyncio applications


## How to install
As any other python package, use pip or include it in the `install_requires` section of your setup.py

```
pip install aiometrics
```

## Sample

Sample application included below makes usage of the default StdoutDriver to print the metrics into the stdout.
```
# sample.py
import asyncio
import datetime
import random

import aiometrics


@aiometrics.trace
@asyncio.coroutine
def echo_delay():
    ms = random.randrange(0, 5000)
    t = ms/1000
    yield from asyncio.sleep(t)
    print(datetime.datetime.now())

@asyncio.coroutine
def main():
    while True:
        yield from echo_delay()

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    asyncio.ensure_future(main())
    loop.run_forever()
    loop.close()
```

Run this sample with the following command:
```python sample.py```

Here is the sample output:
```
2016-06-20 17:56:03.969607
...
2016-06-20 17:57:03.993648
{"instance": {"hostname": "dmo.local", "id": "acf9842e-c127-4844-8026-d7c518076ac2"}, "traces": {"__main__:echo_delay": {"2016-06-20T23:56:00+00": {"count": 24, "avg": 2510.3998333333334, "min": 229.113, "max": 4986.661}}}}
```

This generates a _per-minute_ report listing metrics for every coroutine function decorated with `@aiometrics.trace`. Metrics include (per minute):

- Total number of executions
- Minimum execution time
- Maximum execution time
- Average execution time
