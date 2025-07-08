#!/usr/bin/env python3
"""
Crypto Signal Bot - Terminal Edition
Advanced terminal-based cryptocurrency trading signal bot
"""

import sys
import os
import signal

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def signal_handler(sig, frame):
    """Handle Ctrl+C gracefully"""
    print('\n\n🛑 Shutting down bot...')
    sys.exit(0)

def main():
    try:
        # Register signal handler
        signal.signal(signal.SIGINT, signal_handler)
        
        # Import and run the bot
        from app import main as run_bot
        run_bot()
        
    except KeyboardInterrupt:
        print('\n\n🛑 Bot stopped by user')
        sys.exit(0)
    except Exception as e:
        print(f'\n❌ Error starting bot: {e}')
        sys.exit(1)

if __name__ == '__main__':
    main()
