import time
import threading
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass
import json

@dataclass
class Position:
    symbol: str
    coin: str
    entry_price: float
    current_price: float
    tp1: float
    tp2: float
    stop_loss: float
    entry_level: int
    entry_time: datetime
    status: str  # 'ACTIVE', 'TP1_HIT', 'TP2_HIT', 'STOP_LOSS'
    pnl_percent: float = 0.0
    tp1_hit: bool = False
    is_monitoring: bool = True

class PositionManager:
    def __init__(self, telegram_notifier=None):
        self.positions: Dict[str, Position] = {}
        self.telegram_notifier = telegram_notifier
        self.monitoring_thread = None
        self.monitoring_active = False
        
    def add_position(self, signal: Dict) -> bool:
        """Add new position from signal"""
        symbol = signal['symbol']
        
        # Don't add if already in position
        if symbol in self.positions:
            print(f"⚠️ Already in position for {symbol}")
            return False
        
        position = Position(
            symbol=symbol,
            coin=signal['coin'],
            entry_price=signal['entry_price'],
            current_price=signal['entry_price'],
            tp1=signal['tp1'],
            tp2=signal['tp2'],
            stop_loss=signal['stop_loss'],
            entry_level=signal['entry_level'],
            entry_time=datetime.now(),
            status='ACTIVE'
        )
        
        self.positions[symbol] = position
        print(f"✅ Added position: {symbol} at ${position.entry_price:.6f}")
        
        # Start monitoring if not already running
        if not self.monitoring_active:
            self.start_monitoring()
        
        return True
    
    def update_position_price(self, symbol: str, current_price: float) -> Optional[str]:
        """Update position with current price and check for TP/SL"""
        if symbol not in self.positions:
            return None
        
        position = self.positions[symbol]
        position.current_price = current_price
        position.pnl_percent = ((current_price - position.entry_price) / position.entry_price) * 100
        
        # Check for Take Profit 1 (only if not hit yet)
        if not position.tp1_hit and current_price >= position.tp1:
            position.tp1_hit = True
            position.status = 'TP1_HIT'
            print(f"🎯 {position.coin} TP1 HIT at ${current_price:.6f}")
            
            if self.telegram_notifier:
                self.telegram_notifier.send_position_update(
                    symbol, "TP1_HIT", current_price, position.pnl_percent
                )
            
            return "TP1_HIT"
        
        # Check for Take Profit 2 (close position)
        elif current_price >= position.tp2:
            position.status = 'TP2_HIT'
            position.is_monitoring = False
            print(f"🎯🎯 {position.coin} TP2 HIT at ${current_price:.6f} - Position Closed")
            
            if self.telegram_notifier:
                self.telegram_notifier.send_position_update(
                    symbol, "TP2_HIT", current_price, position.pnl_percent
                )
            
            return "TP2_HIT"
        
        # Check for Stop Loss (close position)
        elif current_price <= position.stop_loss:
            position.status = 'STOP_LOSS'
            position.is_monitoring = False
            print(f"🛑 {position.coin} STOP LOSS at ${current_price:.6f} - Position Closed")
            
            if self.telegram_notifier:
                self.telegram_notifier.send_position_update(
                    symbol, "STOP_LOSS", current_price, position.pnl_percent
                )
            
            return "STOP_LOSS"
        
        return None
    
    def close_position(self, symbol: str) -> bool:
        """Manually close position"""
        if symbol in self.positions:
            position = self.positions[symbol]
            position.is_monitoring = False
            position.status = 'CLOSED'
            print(f"✅ Manually closed position: {position.coin}")
            return True
        return False
    
    def get_active_symbols(self) -> List[str]:
        """Get list of symbols with active positions"""
        return [symbol for symbol, pos in self.positions.items() 
                if pos.is_monitoring and pos.status in ['ACTIVE', 'TP1_HIT']]
    
    def get_positions_summary(self) -> Dict:
        """Get summary of all positions"""
        active_positions = []
        closed_positions = []
        
        for symbol, position in self.positions.items():
            pos_data = {
                'symbol': symbol,
                'coin': position.coin,
                'entry_price': position.entry_price,
                'current_price': position.current_price,
                'pnl_percent': position.pnl_percent,
                'status': position.status,
                'entry_time': position.entry_time.strftime('%H:%M:%S'),
                'tp1_hit': position.tp1_hit
            }
            
            if position.is_monitoring:
                active_positions.append(pos_data)
            else:
                closed_positions.append(pos_data)
        
        return {
            'active_positions': active_positions,
            'closed_positions': closed_positions[-10:],  # Last 10 closed
            'total_active': len(active_positions)
        }
    
    def start_monitoring(self):
        """Start position monitoring thread"""
        if not self.monitoring_active:
            self.monitoring_active = True
            self.monitoring_thread = threading.Thread(target=self._monitor_positions, daemon=True)
            self.monitoring_thread.start()
            print("🔍 Position monitoring started")
    
    def stop_monitoring(self):
        """Stop position monitoring"""
        self.monitoring_active = False
        print("⏹️ Position monitoring stopped")
    
    def _monitor_positions(self):
        """Monitor positions in background thread"""
        from app import signal_bot  # Import here to avoid circular import
        
        while self.monitoring_active:
            try:
                active_symbols = self.get_active_symbols()
                
                if not active_symbols:
                    time.sleep(10)
                    continue
                
                for symbol in active_symbols:
                    try:
                        # Get current price from Binance
                        market_data = signal_bot.get_binance_data(symbol, intervals=["1m"])
                        
                        if market_data and '1m' in market_data:
                            current_price = float(market_data['1m']['close'].iloc[-1])
                            result = self.update_position_price(symbol, current_price)
                            
                            # Clean up closed positions after some time
                            if result in ["TP2_HIT", "STOP_LOSS"]:
                                # Keep position for 5 minutes for UI display, then remove
                                threading.Timer(300, lambda s=symbol: self._cleanup_position(s)).start()
                    
                    except Exception as e:
                        print(f"❌ Error monitoring {symbol}: {e}")
                
                time.sleep(10)  # Check every 10 seconds
                
            except Exception as e:
                print(f"❌ Position monitoring error: {e}")
                time.sleep(30)
    
    def _cleanup_position(self, symbol: str):
        """Remove old closed position"""
        if symbol in self.positions and not self.positions[symbol].is_monitoring:
            del self.positions[symbol]
            print(f"🗑️ Cleaned up closed position: {symbol}")
