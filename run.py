"""Stock Sentinel — entry point. Run with: python run.py"""
import sys

try:
    from stock_sentinel.scheduler import main
    main()
except KeyboardInterrupt:
    print("\nStock Sentinel stopped.")
    sys.exit(0)
