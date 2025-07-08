import time
import threading
from datetime import datetime
from typing import Dict, List, Optional
import requests

class PositionManager:
    def __init__(self, telegram_notifier=None):
        self.active_positions = {}
        self.position_history = []
        self.telegram_notifier = telegram_notifier
        self.monitoring = False
        self.monitor_thread = None
        
        # Trading Statistics
        self.stats = {
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'total_pnl': 0.0,
            'tp1_hits': 0,
            'tp2_hits': 0,
            'sl_hits': 0,
            'breakeven_exits': 0,
            'best_trade': 0.0,
            'worst_trade': 0.0,
            'avg_win': 0.0,
            'avg_loss': 0.0,
            'win_rate': 0.0,
            'profit_factor': 0.0
        }

    def add_position(self, signal: Dict):
        """Add new position from signal"""
        position = {
            'symbol': signal['symbol'],
            'coin': signal['coin'],
            'entry_price': signal['entry_price'],
            'current_price': signal['entry_price'],
            'tp1': signal['tp1'],
            'tp2': signal['tp2'],
            'stop_loss': signal['stop_loss'],
            'original_stop_loss': signal['stop_loss'],
            'entry_level': signal['entry_level'],
            'position_size': signal['position_size'],
            'confidence': signal['confidence'],
            'entry_time': datetime.now().strftime('%H:%M:%S'),
            'entry_timestamp': time.time(),
            'status': 'ACTIVE',
            'tp1_hit': False,
            'tp2_hit': False,
            'sl_hit': False,
            'breakeven_set': False,
            'remaining_size': 100,
            'realized_pnl': 0.0,
            'unrealized_pnl': 0.0,
            'pnl_percent': 0.0,
            'atr_value': signal.get('atr_value', 0),
            'order_book_imbalance': signal.get('order_book_imbalance', 0)
        }
        
        self.active_positions[signal['symbol']] = position
        
        if not self.monitoring:
            self.start_monitoring()
        
        print(f"✅ Position added: {signal['coin']} at ${signal['entry_price']:.6f}")

    def start_monitoring(self):
        """Start monitoring positions"""
        if not self.monitoring:
            self.monitoring = True
            self.monitor_thread = threading.Thread(target=self._monitor_positions, daemon=True)
            self.monitor_thread.start()
            print("📊 Position monitoring started")

    def stop_monitoring(self):
        """Stop monitoring positions"""
        self.monitoring = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=1)
        print("⏹️ Position monitoring stopped")

    def _monitor_positions(self):
        """Monitor active positions for price updates"""
        while self.monitoring:
            try:
                if self.active_positions:
                    for symbol in list(self.active_positions.keys()):
                        current_price = self._get_current_price(symbol)
                        if current_price:
                            self.update_position_price(symbol, current_price)
                
                time.sleep(5)  # Check every 5 seconds
                
            except Exception as e:
                print(f"❌ Error monitoring positions: {e}")
                time.sleep(10)

    def _get_current_price(self, symbol: str) -> Optional[float]:
        """Get current price from Binance"""
        try:
            url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                data = response.json()
                return float(data['price'])
        except Exception as e:
            print(f"❌ Error getting price for {symbol}: {e}")
        return None

    def update_position_price(self, symbol: str, current_price: float):
        """Update position with current price and check exit conditions"""
        if symbol not in self.active_positions:
            return
            
        position = self.active_positions[symbol]
        position['current_price'] = current_price
        
        entry_price = position['entry_price']
        tp1 = position['tp1']
        tp2 = position['tp2']
        stop_loss = position['stop_loss']
        
        # Calculate current PnL
        price_change_percent = ((current_price - entry_price) / entry_price) * 100
        remaining_factor = position['remaining_size'] / 100
        position['unrealized_pnl'] = price_change_percent * remaining_factor
        position['pnl_percent'] = position['realized_pnl'] + position['unrealized_pnl']
        
        # Check TP1 (75% exit + move SL to breakeven)
        if not position['tp1_hit'] and current_price >= tp1:
            self.handle_tp1_hit(symbol, position)
        
        # Check TP2 (full exit)
        elif position['tp1_hit'] and not position['tp2_hit'] and current_price >= tp2:
            self.handle_tp2_hit(symbol, position)
        
        # Check Stop Loss
        elif current_price <= stop_loss:
            self.handle_stop_loss_hit(symbol, position)

    def handle_tp1_hit(self, symbol: str, position: Dict):
        """Handle TP1: Take 75% profit and move SL to breakeven"""
        position['tp1_hit'] = True
        position['status'] = 'TP1_HIT'
        
        tp1_profit_percent = ((position['tp1'] - position['entry_price']) / position['entry_price']) * 100
        position['realized_pnl'] = tp1_profit_percent * 0.75
        position['remaining_size'] = 25
        position['stop_loss'] = position['entry_price']
        position['breakeven_set'] = True
        
        self.stats['tp1_hits'] += 1
        
        print(f"🎯 TP1 HIT: {position['coin']} - 75% profit taken, SL moved to breakeven")
        
        if self.telegram_notifier:
            message = f"""
🎯 **TP1 HIT!** 🎯

💰 **{position['coin']}/USDT**
📈 **75% Position Closed**
💵 **Profit Taken:** +{position['realized_pnl']:.2f}%
🛡️ **Stop Loss:** Moved to breakeven (${position['entry_price']:.6f})
📊 **Remaining:** 25% position for TP2

⏰ **Time:** {datetime.now().strftime('%H:%M:%S')}
            """.strip()
            self.telegram_notifier.send_message(message)

    def handle_tp2_hit(self, symbol: str, position: Dict):
        """Handle TP2: Close remaining 25% position"""
        position['tp2_hit'] = True
        position['status'] = 'TP2_HIT'
        
        tp2_profit_percent = ((position['tp2'] - position['entry_price']) / position['entry_price']) * 100
        final_profit = tp2_profit_percent * 0.25
        position['realized_pnl'] += final_profit
        position['pnl_percent'] = position['realized_pnl']
        position['remaining_size'] = 0
        
        self.stats['tp2_hits'] += 1
        self.complete_trade(symbol, position, 'TP2_HIT')
        
        print(f"🚀 TP2 HIT: {position['coin']} - Full position closed with +{position['pnl_percent']:.2f}% profit")
        
        if self.telegram_notifier:
            message = f"""
🚀 **TP2 HIT - FULL EXIT!** 🚀

💰 **{position['coin']}/USDT**
📈 **Total Profit:** +{position['pnl_percent']:.2f}%
🎯 **TP1 Profit:** +{position['realized_pnl'] - final_profit:.2f}%
🎯 **TP2 Profit:** +{final_profit:.2f}%
✅ **Position:** Fully closed

⏰ **Duration:** {self.get_position_duration(position)}
            """.strip()
            self.telegram_notifier.send_message(message)

    def handle_stop_loss_hit(self, symbol: str, position: Dict):
        """Handle Stop Loss: Either breakeven or loss"""
        position['sl_hit'] = True
        
        if position['breakeven_set']:
            position['status'] = 'BREAKEVEN'
            position['pnl_percent'] = position['realized_pnl']
            position['remaining_size'] = 0
            self.stats['breakeven_exits'] += 1
            
            print(f"⚖️ BREAKEVEN: {position['coin']} - Remaining position closed at entry")
            
            message_text = f"""
⚖️ **BREAKEVEN EXIT** ⚖️

💰 **{position['coin']}/USDT**
📊 **Final Result:** +{position['pnl_percent']:.2f}%
🎯 **TP1 Kept:** +{position['realized_pnl']:.2f}%
🛡️ **Remaining 25%:** Closed at breakeven

⏰ **Duration:** {self.get_position_duration(position)}
            """.strip()
        else:
            position['status'] = 'STOP_LOSS'
            loss_percent = ((position['current_price'] - position['entry_price']) / position['entry_price']) * 100
            position['pnl_percent'] = loss_percent
            position['remaining_size'] = 0
            self.stats['sl_hits'] += 1
            
            print(f"🛑 STOP LOSS: {position['coin']} - Position closed with {loss_percent:.2f}% loss")
            
            message_text = f"""
🛑 **STOP LOSS HIT** 🛑

💰 **{position['coin']}/USDT**
📉 **Loss:** {position['pnl_percent']:.2f}%
💵 **Exit Price:** ${position['current_price']:.6f}
🛡️ **Stop Loss:** ${position['stop_loss']:.6f}

⏰ **Duration:** {self.get_position_duration(position)}
            """.strip()
        
        self.complete_trade(symbol, position, position['status'])
        
        if self.telegram_notifier:
            self.telegram_notifier.send_message(message_text)

    def complete_trade(self, symbol: str, position: Dict, exit_reason: str):
        """Complete trade and update statistics"""
        position['exit_time'] = datetime.now().strftime('%H:%M:%S')
        position['exit_reason'] = exit_reason
        position['duration'] = self.get_position_duration(position)
        
        self.position_history.append(position.copy())
        
        self.stats['total_trades'] += 1
        
        if position['pnl_percent'] > 0:
            self.stats['winning_trades'] += 1
            self.stats['total_pnl'] += position['pnl_percent']
            if position['pnl_percent'] > self.stats['best_trade']:
                self.stats['best_trade'] = position['pnl_percent']
        else:
            self.stats['losing_trades'] += 1
            self.stats['total_pnl'] += position['pnl_percent']
            if position['pnl_percent'] < self.stats['worst_trade']:
                self.stats['worst_trade'] = position['pnl_percent']
        
        self.calculate_advanced_stats()
        
        del self.active_positions[symbol]
        
        print(f"📊 Trade completed: {position['coin']} - {exit_reason} - PnL: {position['pnl_percent']:.2f}%")

    def calculate_advanced_stats(self):
        """Calculate advanced trading statistics"""
        if self.stats['total_trades'] > 0:
            self.stats['win_rate'] = (self.stats['winning_trades'] / self.stats['total_trades']) * 100
        
        if self.stats['winning_trades'] > 0:
            winning_trades = [p['pnl_percent'] for p in self.position_history if p['pnl_percent'] > 0]
            self.stats['avg_win'] = sum(winning_trades) / len(winning_trades)
        
        if self.stats['losing_trades'] > 0:
            losing_trades = [abs(p['pnl_percent']) for p in self.position_history if p['pnl_percent'] < 0]
            self.stats['avg_loss'] = sum(losing_trades) / len(losing_trades)
        
        total_wins = sum([p['pnl_percent'] for p in self.position_history if p['pnl_percent'] > 0])
        total_losses = abs(sum([p['pnl_percent'] for p in self.position_history if p['pnl_percent'] < 0]))
        
        if total_losses > 0:
            self.stats['profit_factor'] = total_wins / total_losses
        else:
            self.stats['profit_factor'] = float('inf') if total_wins > 0 else 0

    def get_position_duration(self, position: Dict) -> str:
        """Calculate position duration"""
        duration_seconds = time.time() - position['entry_timestamp']
        hours = int(duration_seconds // 3600)
        minutes = int((duration_seconds % 3600) // 60)
        
        if hours > 0:
            return f"{hours}h {minutes}m"
        else:
            return f"{minutes}m"

    def get_active_symbols(self) -> List[str]:
        """Get list of symbols with active positions"""
        return list(self.active_positions.keys())

    def close_position(self, symbol: str) -> bool:
        """Manually close a position"""
        if symbol in self.active_positions:
            position = self.active_positions[symbol]
            position['status'] = 'MANUALLY_CLOSED'
            
            price_change_percent = ((position['current_price'] - position['entry_price']) / position['entry_price']) * 100
            remaining_factor = position['remaining_size'] / 100
            final_pnl = position['realized_pnl'] + (price_change_percent * remaining_factor)
            position['pnl_percent'] = final_pnl
            
            self.complete_trade(symbol, position, 'MANUALLY_CLOSED')
            
            if self.telegram_notifier:
                message = f"""
✋ **MANUAL CLOSE** ✋

💰 **{position['coin']}/USDT**
📊 **Final PnL:** {'+' if final_pnl >= 0 else ''}{final_pnl:.2f}%
💵 **Exit Price:** ${position['current_price']:.6f}
⏰ **Duration:** {self.get_position_duration(position)}
                """.strip()
                self.telegram_notifier.send_message(message)
            
            return True
        return False

    def get_positions_summary(self) -> Dict:
        """Get summary including trading statistics"""
        active_positions_list = []
        
        for symbol, position in self.active_positions.items():
            active_positions_list.append({
                'symbol': position['symbol'],
                'coin': position['coin'],
                'entry_price': position['entry_price'],
                'current_price': position['current_price'],
                'tp1': position['tp1'],
                'tp2': position['tp2'],
                'stop_loss': position['stop_loss'],
                'entry_time': position['entry_time'],
                'status': position['status'],
                'tp1_hit': position['tp1_hit'],
                'tp2_hit': position['tp2_hit'],
                'pnl_percent': position['pnl_percent'],
                'remaining_size': position['remaining_size'],
                'realized_pnl': position['realized_pnl'],
                'duration': self.get_position_duration(position)
            })
        
        return {
            'active_positions': active_positions_list,
            'total_positions': len(active_positions_list),
            'statistics': self.stats,
            'recent_trades': self.position_history[-10:]
        }
