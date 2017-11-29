import sys

from sl_monitor.monitor import run

if __name__ == "__main__":
    if len(sys.argv) > 1:
        run(sys.argv[1])
    else:
        run('monitor.local.cfg')
