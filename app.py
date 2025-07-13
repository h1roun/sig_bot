from flask import Flask, render_template, jsonify, request
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time
import threading
import json
from dataclasses import dataclass
from typing import Dict, List, Optional
import ta
import config
from telegram_bot import TelegramNotifier
from position_manager import PositionManager

# Advanced Terminal UI
from rich.console import Console
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.align import Align
from rich import box
import os
import sys

app = Flask(__name__)

@dataclass
class MarketData:
    price: float
    rsi_5m: float
    rsi_15m: float
    rsi_1h: float
    volume: float
    volume_avg: float
    bb_lower: float
    bb_upper: float
    bb_middle: float
    ema_9_15m: float
    ema_21_15m: float
    ema_20_15m: float
    ema_50_daily: float
    weekly_support: float
    btc_trend: str
    macd_5m: float
    macd_signal_5m: float
    macd_histogram_5m: float
    stoch_k: float
    stoch_d: float
    atr_5m: float
    volatility_ratio: float
    btc_strength: float
    timestamp: datetime

class CryptoSignalBot:
    def __init__(self):
        self.running = False
        self.alerts = []
        self.alert_count = 0
        self.last_alert_time = {}
        self.current_data: Dict[str, MarketData] = {}
        self.top_gainers: List[Dict] = []
        self.scanning_symbols: List[str] = []
        self.headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        self.current_scanning_symbol = None
        self.scan_stats = {
            'total_scanned': 0,
            'signals_found': 0,
            'scan_cycles': 0,
            'last_scan_time': None
        }
        
        # Initialize Rich Console
        self.console = Console()
        self.layout = Layout()
        
        # Initialize Telegram and Position Manager
        try:
            self.telegram_notifier = TelegramNotifier(
                config.TELEGRAM_BOT_TOKEN, 
                config.TELEGRAM_CHAT_ID
            )
            self.log_message("✅ Telegram notifier initialized", "success")
        except Exception as e:
            self.log_message(f"⚠️ Telegram not configured: {e}", "warning")
            self.telegram_notifier = None
        
        self.position_manager = PositionManager(self.telegram_notifier)
        
        # Setup terminal layout
        self.setup_layout()
        
    def setup_layout(self):
        """Setup the terminal layout optimized for 14" MacBook - more horizontal"""
        self.layout.split_column(
            Layout(name="header", size=2),
            Layout(name="body"),
            Layout(name="footer", size=2)
        )
        
        # More horizontal layout - 4 columns for more details
        self.layout["body"].split_row(
            Layout(name="left", ratio=1),      # Stats + Positions
            Layout(name="middle", ratio=1),    # Signals + Logs  
            Layout(name="right", ratio=2),     # Gainers table
            Layout(name="details", ratio=1)    # Top conditions
        )
        
        # Left column: Stats + Positions
        self.layout["left"].split_column(
            Layout(name="stats", size=10),
            Layout(name="positions")
        )
        
        # Middle column: Signals + Logs
        self.layout["middle"].split_column(
            Layout(name="signals", ratio=2),
            Layout(name="logs", ratio=1)
        )
        
        # Right column: Just gainers
        self.layout["right"].split_column(
            Layout(name="gainers")
        )
        
        # Details column: Top conditions instead of current scan
        self.layout["details"].split_column(
            Layout(name="conditions_detail")  # Remove current_scan, just show top conditions
        )

    def log_message(self, message: str, level: str = "info"):
        """Add log message with timestamp - no emojis"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.alerts.insert(0, {
            'time': timestamp,
            'message': message.replace('✅', '[OK]').replace('❌', '[ERR]').replace('⚠️', '[WARN]').replace('🔄', '[INFO]').replace('🚨', '[SIGNAL]'),
            'level': level
        })
        # Keep only last 30 messages for smaller screen
        self.alerts = self.alerts[:30]

    def create_header(self) -> Panel:
        """Create header panel - compact for 14" screen"""
        title = "CRYPTO SIGNAL BOT - TERMINAL EDITION"
        status = "ONLINE" if self.running else "OFFLINE"
        
        header_text = Text()
        header_text.append(f"{title} | ", style="bold cyan")
        header_text.append(f"Status: {status} | ", style="bold green" if self.running else "bold red")
        header_text.append(f"Coins: {len(self.scanning_symbols)} | ", style="white")
        header_text.append(f"Signals: {self.scan_stats['signals_found']} | ", style="yellow")
        header_text.append(f"Positions: {len(self.position_manager.active_positions)}", style="blue")
        
        return Panel(Align.center(header_text), style="blue")

    def create_stats_panel(self) -> Panel:
        """Create trading statistics panel - more compact"""
        stats = self.position_manager.stats
        
        table = Table(title="Trading Stats", box=box.SIMPLE, show_header=False)
        table.add_column("", style="cyan", width=8)
        table.add_column("", style="white", width=6)
        
        table.add_row("Trades", str(stats['total_trades']))
        table.add_row("Win%", f"{stats['win_rate']:.1f}%")
        table.add_row("PnL", f"{stats['total_pnl']:+.1f}%")
        table.add_row("TP1", str(stats['tp1_hits']))
        table.add_row("TP2", str(stats['tp2_hits']))
        table.add_row("SL", str(stats['sl_hits']))
        table.add_row("Best", f"+{stats['best_trade']:.1f}%")
        table.add_row("PF", f"{stats['profit_factor']:.1f}")
        
        return Panel(table, style="green")

    def create_positions_panel(self) -> Panel:
        """Create active positions panel - more compact"""
        table = Table(title="Positions", box=box.SIMPLE, show_header=False)
        table.add_column("", style="cyan", width=5)
        table.add_column("", style="white", width=6)
        table.add_column("", style="white", width=5)
        
        for symbol, position in list(self.position_manager.active_positions.items())[:5]:  # Max 5 positions
            pnl_style = "green" if position['pnl_percent'] >= 0 else "red"
            status = position['status'].replace('TP1_HIT', 'TP1').replace('ACTIVE', 'OPEN')[:4]
            
            table.add_row(
                position['coin'][:5],
                f"${position['entry_price']:.3f}",
                Text(f"{position['pnl_percent']:+.1f}%", style=pnl_style)
            )
        
        if not self.position_manager.active_positions:
            table.add_row("None", "", "")
        
        return Panel(table, style="blue")

    def create_gainers_panel(self) -> Panel:
        """Updated gainers panel with better error handling for N/A values"""
        table = Table(title="Top 35 Gainers", box=box.SIMPLE)
        table.add_column("Coin", style="cyan", width=4)
        table.add_column("Price", style="white", width=7)
        table.add_column("Chg%", style="white", width=5)
        table.add_column("Core", style="white", width=4)  # Changed from "C" to "Core"
        table.add_column("Vol", style="white", width=5)
        table.add_column("RSI", style="white", width=4)
        table.add_column("Status", style="white", width=9)  # Increased width for more detailed status
        
        display_gainers = self.top_gainers[:35]
        
        for gainer in display_gainers:
            symbol = gainer['symbol']
            data = self.current_data.get(symbol)
            
            if data and isinstance(data, MarketData):  # Ensure data is valid and of correct type
                try:
                    conditions = self.check_strategy_conditions(data)
                    core_conditions = ['bb_touch', 'rsi_oversold', 'macd_momentum', 'stoch_recovery', 'trend_alignment']
                    core_conditions_met = sum(conditions[cond] for cond in core_conditions)
                    
                    # Better error handling for volume calculation
                    if hasattr(data, 'volume') and hasattr(data, 'volume_avg') and data.volume_avg > 0:
                        volume_str = f"{data.volume/data.volume_avg:.1f}x"
                        vol_ok = data.volume/data.volume_avg > 0.8  # Simple volume check
                    else:
                        volume_str = "Wait"  # Change "N/A" to "Wait" for clarity
                        vol_ok = False
                    
                    # Better error handling for RSI
                    if hasattr(data, 'rsi_5m') and not pd.isna(data.rsi_5m):
                        rsi_str = f"{data.rsi_5m:.0f}"
                    else:
                        rsi_str = "Wait"  # Change "N/A" to "Wait" for clarity
                    
                    # Get order book imbalance
                    imbalance_ratio = self.get_order_book_imbalance(symbol)
                    order_book_ok = imbalance_ratio is not None and imbalance_ratio >= config.MIN_ORDER_BOOK_IMBALANCE
                    
                    # Get reward:risk ratio
                    market_data = self.get_binance_data(symbol)
                    if market_data and '5m' in market_data:
                        atr_levels = self.calculate_atr_levels(market_data, data.price)
                        reward_risk_ratio = atr_levels.get('reward_risk_ratio', 1.0)
                        rr_ok = reward_risk_ratio >= 1.2
                    else:
                        reward_risk_ratio = 0
                        rr_ok = False
                        
                    # Calculate signal score (simplified version for the table)
                    score = core_conditions_met * 20  # Base score from core conditions
                    score_ok = score >= 80
                    
                except Exception as e:
                    # Handle any unexpected errors in condition checking
                    self.log_message(f"Error processing {symbol}: {str(e)[:20]}", "error")
                    core_conditions_met = 0
                    volume_str = "Err"  # Error indicator
                    rsi_str = "Err"  # Error indicator
                    order_book_ok = False
                    rr_ok = False
                    score_ok = False
            else:
                core_conditions_met = 0
                volume_str = "Scan"  # Clearer indication that scan is pending
                rsi_str = "Scan"  # Clearer indication that scan is pending
                order_book_ok = False
                rr_ok = False
                score_ok = False
            
            change_style = "green" if gainer['change_24h'] > 0 else "red"
            conditions_style = "green" if core_conditions_met >= 5 else "yellow" if core_conditions_met >= 4 else "white"
            
            # Enhanced status display with filter info
            if symbol == f"{self.current_scanning_symbol}USDT":
                status = "SCANNING"
                status_style = "yellow"
            elif core_conditions_met == 5:
                if order_book_ok and rr_ok and score_ok:
                    status = "✅ SIGNAL"
                    status_style = "bold green"
                elif not order_book_ok:
                    status = "⏳ OB Wait"
                    status_style = "red"
                elif not rr_ok:
                    status = "⏳ RR Wait" 
                    status_style = "red"
                else:
                    status = "⏳ Almost"
                    status_style = "red"
            elif core_conditions_met >= 4:
                status = "🔄 Ready"
                status_style = "yellow"
            elif core_conditions_met >= 3:
                status = "👀 Watching"
                status_style = "cyan"
            else:
                status = "Tracking"
                status_style = "white"
            
            table.add_row(
                gainer['coin'][:4],
                f"${gainer['price']:.3f}",
                Text(f"{gainer['change_24h']:+.1f}", style=change_style),
                Text(f"{core_conditions_met}/5", style=conditions_style),  # Show core conditions
                volume_str,
                rsi_str,
                Text(status, style=status_style)
            )
        
        return Panel(table, style="magenta")

    def create_current_scan_panel(self) -> Panel:
        """Create current scanning coin details"""
        if not self.current_scanning_symbol:
            return Panel(
                Align.center(Text("No coin being scanned", style="dim")),
                title="Current Scan",
                style="blue"
            )
        
        symbol = f"{self.current_scanning_symbol}USDT"
        data = self.current_data.get(symbol)
        
        if not data:
            return Panel(
                Align.center(Text(f"Scanning {self.current_scanning_symbol}...", style="yellow")),
                title="Current Scan",
                style="blue"
            )
        
        # Create detailed info about current scan
        table = Table(box=box.SIMPLE, show_header=False)
        table.add_column("", style="cyan", width=8)
        table.add_column("", style="white", width=10)
        
        table.add_row("Coin", self.current_scanning_symbol)
        table.add_row("Price", f"${data.price:.6f}")
        table.add_row("RSI 5m", f"{data.rsi_5m:.1f}")
        table.add_row("RSI 15m", f"{data.rsi_15m:.1f}")
        table.add_row("RSI 1h", f"{data.rsi_1h:.1f}")
        table.add_row("Volume", f"{data.volume/data.volume_avg:.2f}x avg")
        table.add_row("BB Dist", f"{((data.price - data.bb_lower)/data.bb_lower)*100:.2f}%")
        
        return Panel(table, title=f"Scanning: {self.current_scanning_symbol}", style="blue")

    def create_conditions_detail_panel(self) -> Panel:
        """Updated conditions panel with additional filters display"""
        # Find top 3 coins with most conditions met
        top_coins = []
        
        for gainer in self.top_gainers[:20]:
            symbol = gainer['symbol']
            data = self.current_data.get(symbol)
            if data:
                conditions = self.check_strategy_conditions(data)
                core_conditions = ['bb_touch', 'rsi_oversold', 'macd_momentum', 'stoch_recovery', 'trend_alignment']
                core_conditions_met = sum(conditions[cond] for cond in core_conditions)
                total_conditions = sum(conditions.values())
                
                # Calculate signal score for filtering
                score = core_conditions_met * 20  # Base score from core conditions
                
                # Add bonus points for strong signals
                if conditions['bb_touch'] and data.price < data.bb_lower * 1.003:  # Very close to BB
                    score += 10
                if conditions['stoch_recovery'] and data.stoch_k < 25:  # Very oversold
                    score += 10
                if data.rsi_5m < 35:  # Very oversold RSI
                    score += 10
                if data.macd_5m > data.macd_signal_5m and data.macd_histogram_5m > 0:  # Strong MACD
                    score += 10
                
                # Get order book imbalance
                imbalance_ratio = self.get_order_book_imbalance(symbol)
                
                # Get reward:risk ratio
                market_data = self.get_binance_data(symbol)
                if market_data and '5m' in market_data:
                    atr_levels = self.calculate_atr_levels(market_data, data.price)
                    reward_risk_ratio = atr_levels.get('reward_risk_ratio', 1.0)
                else:
                    reward_risk_ratio = 0
                
                if core_conditions_met >= 3:  # Only include coins with at least 3 core conditions
                    top_coins.append({
                        'coin': gainer['coin'],
                        'symbol': symbol,
                        'core_conditions_met': core_conditions_met,
                        'total_conditions': total_conditions,
                        'conditions': conditions,
                        'data': data,
                        'price': gainer['price'],
                        'change': gainer['change_24h'],
                        'score': score,
                        'imbalance_ratio': imbalance_ratio if imbalance_ratio is not None else 0,
                        'reward_risk_ratio': reward_risk_ratio
                    })
        
        # Sort by core conditions met, then signal score
        top_coins.sort(key=lambda x: (x['core_conditions_met'], x['score']), reverse=True)
        top_3_coins = top_coins[:3]
        
        if not top_3_coins:
            return Panel(
                Align.center(Text("No conditions met yet", style="dim")),
                title="Top Conditions",
                style="white"
            )
        
        # Create vertical layout with one table for each coin
        tables = []
        
        for coin_info in top_3_coins:
            conditions = coin_info['conditions']
            data = coin_info['data']
            
            # Create detailed table for this coin with signal filters status
            score_status = "✅" if coin_info['score'] >= 80 else "❌"
            ob_status = "✅" if coin_info['imbalance_ratio'] >= config.MIN_ORDER_BOOK_IMBALANCE else "❌"
            rr_status = "✅" if coin_info['reward_risk_ratio'] >= 1.2 else "❌"
            
            title_style = "bold green" if (
                coin_info['core_conditions_met'] == 5 and 
                coin_info['score'] >= 80 and 
                coin_info['imbalance_ratio'] >= config.MIN_ORDER_BOOK_IMBALANCE and
                coin_info['reward_risk_ratio'] >= 1.2
            ) else "bold yellow" if coin_info['core_conditions_met'] >= 4 else "cyan"
            
            # Enhanced title with filter status
            title = f"{coin_info['coin']} - {coin_info['core_conditions_met']}/5 Core"
            
            coin_table = Table(
                title=title, 
                box=box.SIMPLE, 
                title_style=title_style
            )
            
            coin_table.add_column("Condition", style="white", width=10)
            coin_table.add_column("Status", style="white", width=3)
            coin_table.add_column("Value", style="white", width=7)
            coin_table.add_column("Target", style="white", width=7)
            
            # Price and change info
            coin_table.add_row(
                "Price",
                "",
                f"${coin_info['price']:.4f}",
                f"{coin_info['change']:+.1f}%"
            )
            
            # 1. BB Touch (CORE)
            bb_distance = ((data.price - data.bb_lower) / data.bb_lower) * 100
            bb_style = "green" if conditions['bb_touch'] else "red"
            coin_table.add_row(
                "BB Touch*",
                Text("✓" if conditions['bb_touch'] else "✗", style=bb_style),
                f"{bb_distance:.2f}%",
                "< 1.5%"
            )
            
            # 2. RSI Oversold (CORE)
            rsi_style = "green" if conditions['rsi_oversold'] else "red"
            coin_table.add_row(
                "RSI Oversold*",
                Text("✓" if conditions['rsi_oversold'] else "✗", style=rsi_style),
                f"{data.rsi_5m:.1f}",
                "25-55"
            )
            
            # 3. MACD Momentum (CORE)
            macd_style = "green" if conditions['macd_momentum'] else "red"
            coin_table.add_row(
                "MACD Mom*",
                Text("✓" if conditions['macd_momentum'] else "✗", style=macd_style),
                f"{data.macd_histogram_5m:.4f}",
                "> -0.001"
            )
            
            # 4. Stoch Recovery (CORE)
            stoch_style = "green" if conditions['stoch_recovery'] else "red"
            coin_table.add_row(
                "Stoch Rec*",
                Text("✓" if conditions['stoch_recovery'] else "✗", style=stoch_style),
                f"{data.stoch_k:.1f}K/{data.stoch_d:.1f}D",
                "< 40, Recov"
            )
            
            # 5. Trend Alignment (CORE)
            trend_style = "green" if conditions['trend_alignment'] else "red"
            coin_table.add_row(
                "Trend*",
                Text("✓" if conditions['trend_alignment'] else "✗", style=trend_style),
                data.btc_trend,
                "Aligned"
            )
            
            # Add separator for signal filters
            coin_table.add_row("", "", "", "")
            
            # Add additional filters section
            coin_table.add_row(
                "Signal Score",
                Text(score_status, style="green" if coin_info['score'] >= 80 else "red"),
                f"{coin_info['score']}/130",
                "≥ 80"
            )
            
            coin_table.add_row(
                "Order Book",
                Text(ob_status, style="green" if coin_info['imbalance_ratio'] >= config.MIN_ORDER_BOOK_IMBALANCE else "red"),
                f"{coin_info['imbalance_ratio']:.2f}",
                f"≥ {config.MIN_ORDER_BOOK_IMBALANCE}"
            )
            
            coin_table.add_row(
                "Reward:Risk",
                Text(rr_status, style="green" if coin_info['reward_risk_ratio'] >= 1.2 else "red"),
                f"{coin_info['reward_risk_ratio']:.2f}",
                "≥ 1.2"
            )
            
            tables.append(coin_table)
        
        # Fill remaining slots
        while len(tables) < 3:
            empty_table = Table(box=None)
            empty_table.add_row("")
            tables.append(empty_table)
        
        # Stack tables vertically
        layout = Table.grid()
        for table in tables:
            layout.add_row(table)
        
        return Panel(
            layout, 
            title="Core Conditions + Signal Filters (ALL required)", 
            style="green" if top_3_coins and top_3_coins[0]['core_conditions_met'] == 5 else "white"
        )

    def create_signals_panel(self) -> Panel:
        """Create recent signals panel with more details"""
        table = Table(title="Recent Signals", box=box.SIMPLE)
        table.add_column("Time", style="cyan", width=5)
        table.add_column("Coin", style="white", width=6)
        table.add_column("Level", style="white", width=5)
        table.add_column("Entry", style="white", width=8)
        
        signal_alerts = [alert for alert in self.alerts if 'SIGNAL' in alert['message']][:6]
        
        for alert in signal_alerts:
            message_parts = alert['message'].split()
            if len(message_parts) >= 3:
                coin = message_parts[1] if len(message_parts) > 1 else "N/A"
                level = message_parts[-1] if "Level" in alert['message'] else "1"
                entry = "Active" if "ENTRY" in alert['message'] else "N/A"
                
                table.add_row(
                    alert['time'][:5],
                    coin[:6],
                    level,
                    entry
                )
        
        if not signal_alerts:
            table.add_row("--:--", "None", "0", "Waiting")
        
        return Panel(table, style="yellow")

    def create_logs_panel(self) -> Panel:
        """Create enhanced logs panel with proper updating"""
        table = Table(title="System Status", box=box.SIMPLE, show_header=False)
        table.add_column("", style="cyan", width=5)
        table.add_column("", style="white")
        
        # Show scan progress and system status with proper updates
        if self.running:
            # Calculate progress properly
            total_symbols = len(self.scanning_symbols) if self.scanning_symbols else 35
            scanned_symbols = len([s for s in self.scanning_symbols if s in self.current_data and self.current_data[s] is not None])
            scan_progress = f"{scanned_symbols}/{total_symbols}"
            
            # Show current scanning status
            if self.current_scanning_symbol:
                current_status = f"Scanning {self.current_scanning_symbol}"
            else:
                current_status = "Between scans"
            
            table.add_row("Progress", scan_progress)
            table.add_row("Status", current_status)
            table.add_row("Cycles", str(self.scan_stats['scan_cycles']))
            table.add_row("Signals", str(self.scan_stats['signals_found']))
            
            # Show latest scan time
            if self.scan_stats['last_scan_time']:
                last_scan = self.scan_stats['last_scan_time'].strftime('%H:%M:%S')
                table.add_row("Last", last_scan)
        else:
            table.add_row("Status", "OFFLINE")
            table.add_row("Scanned", "0/0")
            table.add_row("Cycles", "0")
            table.add_row("Signals", "0")
        
        return Panel(table, style="white")

    def render_dashboard(self):
        """Render the complete dashboard with all fixes"""
        self.layout["header"].update(self.create_header())
        self.layout["stats"].update(self.create_stats_panel())
        self.layout["positions"].update(self.create_positions_panel())
        self.layout["signals"].update(self.create_signals_panel())
        self.layout["gainers"].update(self.create_gainers_panel())
        self.layout["logs"].update(self.create_logs_panel())
        self.layout["conditions_detail"].update(self.create_conditions_detail_panel())
        self.layout["footer"].update(self.create_footer())
        
        return self.layout

    def create_footer(self) -> Panel:
        """Create enhanced footer with better info"""
        footer_text = Text()
        
        if self.current_scanning_symbol:
            symbol = f"{self.current_scanning_symbol}USDT"
            data = self.current_data.get(symbol)
            if data:
                conditions = self.check_strategy_conditions(data)
                core_conditions = ['bb_touch', 'rsi_oversold', 'macd_momentum', 'stoch_recovery', 'trend_alignment']
                core_conditions_met = sum(conditions[cond] for cond in core_conditions)
                total_conditions = sum(conditions.values())
                # Fixed to show correct condition count (5 core + 1 bonus)
                footer_text.append(f"Scanning: {self.current_scanning_symbol} ({core_conditions_met}/5 core, {total_conditions}/6 total) | ", style="yellow")
            else:
                footer_text.append(f"Scanning: {self.current_scanning_symbol} | ", style="yellow")
        else:
            footer_text.append("Scanner idle | ", style="dim")
        
        # Better progress tracking
        total_symbols = len(self.scanning_symbols) if self.scanning_symbols else 35
        scanned_symbols = len([s for s in self.scanning_symbols if s in self.current_data and self.current_data[s] is not None])
        
        footer_text.append(f"Progress: {scanned_symbols}/{total_symbols} | ", style="cyan")
        footer_text.append(f"Cycles: {self.scan_stats['scan_cycles']} | ", style="green")
        footer_text.append(f"Signals: {self.scan_stats['signals_found']} | ", style="magenta")
        footer_text.append(f"{datetime.now().strftime('%H:%M:%S')} | ", style="white")
        footer_text.append("Ctrl+C to stop", style="red")
        
        return Panel(Align.center(footer_text), style="blue")

    def get_top_gainers(self) -> List[Dict]:
        """Fetch top 35 daily gainers from Binance"""
        try:
            url = "https://api.binance.com/api/v3/ticker/24hr"
            response = requests.get(url, headers=self.headers, timeout=15)
            response.raise_for_status()
            
            all_tickers = response.json()
            filtered_tickers = []
            
            skip_coins = [
                'USDC', 'BUSD', 'TUSD', 'USDP', 'FDUSD', 'USDT', 'DAI', 
                'PAXG', 'PAX', 'USDK', 'SUSD', 'GUSD', 'HUSD', 'USDN',
                'UST', 'FRAX', 'LUSD', 'TRIBE', 'FEI', 'ALUSD', 'CUSD',
                'GOLD', 'XAUT'
            ]
            
            for ticker in all_tickers:
                symbol = ticker['symbol']
                
                if not symbol.endswith('USDT'):
                    continue
                    
                symbol_base = symbol.replace('USDT', '')
                if any(stable in symbol_base for stable in skip_coins):
                    continue
                
                try:
                    price = float(ticker['lastPrice'])
                    volume = float(ticker['volume'])
                    quote_volume = float(ticker['quoteVolume'])
                    change_percent = float(ticker['priceChangePercent'])
                    trades = int(ticker['count'])
                    
                    if (price > 0.00001 and change_percent > -95 and change_percent < 5000):
                        filtered_tickers.append({
                            'symbol': symbol,
                            'coin': symbol_base,
                            'price': price,
                            'change_24h': change_percent,
                            'volume': volume,
                            'volume_usdt': quote_volume,
                            'high_24h': float(ticker['highPrice']),
                            'low_24h': float(ticker['lowPrice']),
                            'trades': trades
                        })
                        
                except (ValueError, KeyError):
                    continue
            
            # Increase to top 35 gainers
            top_gainers = sorted(filtered_tickers, key=lambda x: x['change_24h'], reverse=True)[:35]
            return top_gainers
            
        except Exception as e:
            self.log_message(f"Error fetching gainers: {e}", "error")
            return []

    def get_binance_data(self, symbol=None, intervals=["5m", "15m", "1h", "1d"]):
        """Fetch real-time data from Binance API with better error handling"""
        base_url = "https://api.binance.com/api/v3/klines"
        data = {}
        
        for interval in intervals:
            try:
                params = {
                    'symbol': symbol,
                    'interval': interval,
                    'limit': 200
                }
                response = requests.get(base_url, params=params, timeout=10)
                if response.status_code == 200:
                    klines = response.json()
                    if len(klines) < 50:  # Ensure we have enough data
                        continue
                        
                    df = pd.DataFrame(klines, columns=[
                        'timestamp', 'open', 'high', 'low', 'close', 'volume',
                        'close_time', 'quote_asset_volume', 'number_of_trades',
                        'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
                    ])
                    df = df.astype({
                        'open': float, 'high': float, 'low': float, 
                        'close': float, 'volume': float
                    })
                    data[interval] = df
            except Exception as e:
                self.log_message(f"Error fetching {interval} data for {symbol}: {str(e)[:20]}", "error")
                continue
    
        return data  # Fixed: Added missing return statement

    def calculate_indicators(self, data: Dict[str, pd.DataFrame]) -> Optional[MarketData]:
        """COMPLETELY REDESIGNED: Ultra-robust indicator calculation with fallbacks for every value"""
        try:
        # First check for required intervals
            required_intervals = ["5m", "15m", "1h", "1d"]
            
            # Check if we have all required intervals
            for interval in required_intervals:
                if interval not in data or len(data[interval]) < 50:
                    self.log_message(f"Missing or insufficient data for {interval}", "warning")
                    return None
            
            # Current price is critical - if we can't get this, nothing works
            try:
                current_price = float(data['5m']['close'].iloc[-1])
                if pd.isna(current_price) or current_price <= 0:
                    self.log_message("Invalid price", "error")
                    return None
            except Exception as e:
                self.log_message(f"Critical error getting price: {str(e)}", "error")
                return None
            
            # ------ CALCULATE ALL INDICATORS WITH EXTENSIVE FALLBACKS ------
            
            # RSI indicators with fallbacks
            try:
                rsi_5m = ta.momentum.RSIIndicator(data['5m']['close'], window=7).rsi().iloc[-1]
                if pd.isna(rsi_5m):
                    # Try different window
                    rsi_5m = ta.momentum.RSIIndicator(data['5m']['close'], window=14).rsi().iloc[-1]
                    if pd.isna(rsi_5m):
                        rsi_5m = 50  # Default to neutral
                        self.log_message("Using default RSI 5m value", "warning")
            except Exception:
                rsi_5m = 50
                self.log_message("RSI 5m calculation failed, using default", "warning")
                
            try:
                rsi_15m = ta.momentum.RSIIndicator(data['15m']['close'], window=7).rsi().iloc[-1]
                if pd.isna(rsi_15m):
                    rsi_15m = rsi_5m  # Fall back to 5m value
            except Exception:
                rsi_15m = rsi_5m
                
            try:
                rsi_1h = ta.momentum.RSIIndicator(data['1h']['close'], window=14).rsi().iloc[-1]
                if pd.isna(rsi_1h):
                    rsi_1h = rsi_15m
            except Exception:
                rsi_1h = rsi_15m
            
            # Bollinger Bands with fallbacks
            try:
                bb_5m = ta.volatility.BollingerBands(data['5m']['close'], window=20, window_dev=2)
                bb_lower = bb_5m.bollinger_lband().iloc[-1]
                bb_upper = bb_5m.bollinger_hband().iloc[-1]
                bb_middle = bb_5m.bollinger_mavg().iloc[-1]
                
                if pd.isna(bb_lower) or pd.isna(bb_upper) or pd.isna(bb_middle):
                    # Try shorter window
                    bb_5m = ta.volatility.BollingerBands(data['5m']['close'], window=14, window_dev=2)
                    bb_lower = bb_5m.bollinger_lband().iloc[-1]
                    bb_upper = bb_5m.bollinger_hband().iloc[-1]
                    bb_middle = bb_5m.bollinger_mavg().iloc[-1]
                    
                    if pd.isna(bb_lower) or pd.isna(bb_upper) or pd.isna(bb_middle):
                        # Fall back to simple percentage bands
                        bb_middle = current_price
                        bb_lower = current_price * 0.98  # 2% below price
                        bb_upper = current_price * 1.02  # 2% above price
                        self.log_message("Using default BB values", "warning")
            except Exception:
                bb_middle = current_price
                bb_lower = current_price * 0.98
                bb_upper = current_price * 1.02
                self.log_message("BB calculation failed, using defaults", "warning")
            
            # EMAs with fallbacks
            try:
                ema_9_15m = ta.trend.EMAIndicator(data['15m']['close'], window=9).ema_indicator().iloc[-1]
                if pd.isna(ema_9_15m):
                    ema_9_15m = current_price
            except Exception:
                ema_9_15m = current_price
                
            try:
                ema_21_15m = ta.trend.EMAIndicator(data['15m']['close'], window=21).ema_indicator().iloc[-1]
                if pd.isna(ema_21_15m):
                    ema_21_15m = current_price
            except Exception:
                ema_21_15m = current_price
                
            try:
                ema_20_15m = ta.trend.EMAIndicator(data['15m']['close'], window=20).ema_indicator().iloc[-1]
                if pd.isna(ema_20_15m):
                    ema_20_15m = current_price
            except Exception:
                ema_20_15m = current_price
                
            try:
                ema_50_daily = ta.trend.EMAIndicator(data['1d']['close'], window=50).ema_indicator().iloc[-1]
                if pd.isna(ema_50_daily):
                    ema_50_daily = current_price
            except Exception:
                ema_50_daily = current_price
            
            # MACD
            try:
                macd_indicator = ta.trend.MACD(data['5m']['close'], window_slow=26, window_fast=12, window_sign=9)
                macd_5m = macd_indicator.macd().iloc[-1]
                macd_signal_5m = macd_indicator.macd_signal().iloc[-1]
                macd_histogram_5m = macd_indicator.macd_diff().iloc[-1]
                
                if pd.isna(macd_5m) or pd.isna(macd_signal_5m) or pd.isna(macd_histogram_5m):
                    # Try alternative windows
                    macd_indicator = ta.trend.MACD(data['5m']['close'], window_slow=24, window_fast=12, window_sign=9)
                    macd_5m = macd_indicator.macd().iloc[-1]
                    macd_signal_5m = macd_indicator.macd_signal().iloc[-1]
                    macd_histogram_5m = macd_indicator.macd_diff().iloc[-1]
                    
                    if pd.isna(macd_5m) or pd.isna(macd_signal_5m) or pd.isna(macd_histogram_5m):
                        # Default values - slightly positive for mild buy bias
                        macd_5m = 0.0001
                        macd_signal_5m = 0
                        macd_histogram_5m = 0.0001
                        self.log_message("Using default MACD values", "warning")
            except Exception:
                macd_5m = 0.0001
                macd_signal_5m = 0
                macd_histogram_5m = 0.0001
                self.log_message("MACD calculation failed, using defaults", "warning")
            
            # Stochastic
            try:
                stoch_indicator = ta.momentum.StochasticOscillator(
                    data['5m']['high'], data['5m']['low'], data['5m']['close'], 
                    window=14, smooth_window=3
                )
                stoch_k = stoch_indicator.stoch().iloc[-1]
                stoch_d = stoch_indicator.stoch_signal().iloc[-1]
                
                if pd.isna(stoch_k) or pd.isna(stoch_d):
                    # Try alternative windows
                    stoch_indicator = ta.momentum.StochasticOscillator(
                        data['5m']['high'], data['5m']['low'], data['5m']['close'], 
                        window=12, smooth_window=3
                    )
                    stoch_k = stoch_indicator.stoch().iloc[-1]
                    stoch_d = stoch_indicator.stoch_signal().iloc[-1]
                    
                    if pd.isna(stoch_k) or pd.isna(stoch_d):
                        # Default to mid-range values
                        stoch_k = 40
                        stoch_d = 40
                        self.log_message("Using default Stochastic values", "warning")
            except Exception:
                stoch_k = 40
                stoch_d = 40
                self.log_message("Stochastic calculation failed, using defaults", "warning")
            
            # ATR with fallbacks
            try:
                atr_indicator = ta.volatility.AverageTrueRange(
                    data['5m']['high'], data['5m']['low'], data['5m']['close'], 
                    window=14
                )
                atr_5m = atr_indicator.average_true_range().iloc[-1]
                
                if pd.isna(atr_5m):
                    # Try different window
                    atr_indicator = ta.volatility.AverageTrueRange(
                        data['5m']['high'], data['5m']['low'], data['5m']['close'], 
                        window=7
                    )
                    atr_5m = atr_indicator.average_true_range().iloc[-1]
                    
                    if pd.isna(atr_5m):
                        # Fallback to percentage of price
                        atr_5m = current_price * 0.005  # 0.5% of price
                        self.log_message("Using default ATR value", "warning")
            except Exception:
                atr_5m = current_price * 0.005
                self.log_message("ATR calculation failed, using default", "warning")
            
            # Volume analysis with fallbacks
            try:
                current_volume = float(data['5m']['volume'].iloc[-1])
                volume_avg = data['5m']['volume'].rolling(20).mean().iloc[-1]
                
                if pd.isna(current_volume) or current_volume <= 0:
                    current_volume = 1.0
                    self.log_message("Invalid volume, using default", "warning")
                    
                if pd.isna(volume_avg) or volume_avg <= 0:
                    volume_avg = current_volume
                    self.log_message("Invalid avg volume, using current", "warning")
            except Exception:
                current_volume = 1.0
                volume_avg = 1.0
                self.log_message("Volume calculation failed, using defaults", "warning")
            
            # Support level with fallbacks
            try:
                weekly_support = data['1d']['low'].tail(7).min()
                if pd.isna(weekly_support) or weekly_support <= 0:
                    weekly_support = current_price * 0.95  # 5% below price
            except Exception:
                weekly_support = current_price * 0.95
            
            # BTC trend with fallbacks
            try:
                price_vs_ema50 = (current_price - ema_50_daily) / ema_50_daily * 100
                btc_trend = "UP" if price_vs_ema50 > -2 else "DOWN"
                btc_strength = abs(price_vs_ema50)
            except Exception:
                btc_trend = "UP"  # Default to bullish bias
                btc_strength = 1.0
            
            # Volatility ratio with fallbacks
            try:
                if bb_middle > 0:
                    bb_width = (bb_upper - bb_lower) / bb_middle
                else:
                    bb_width = 0.04  # Default 4% width
                    
                # Default to 1.0 (normal volatility) if calculation fails
                volatility_ratio = 1.0
                
                # Only calculate if we have valid BB values
                if bb_width > 0:
                    try:
                        historical_bb_width = []
                        for i in range(20):
                            hist_bb = ta.volatility.BollingerBands(
                                data['5m']['close'].iloc[-(20-i):], window=20, window_dev=2
                            )
                            hist_width = (hist_bb.bollinger_hband().iloc[-1] - hist_bb.bollinger_lband().iloc[-1]) / hist_bb.bollinger_mavg().iloc[-1]
                            if not pd.isna(hist_width) and hist_width > 0:
                                historical_bb_width.append(hist_width)
                        
                        if len(historical_bb_width) > 0:
                            avg_bb_width = sum(historical_bb_width) / len(historical_bb_width)
                            if avg_bb_width > 0:
                                volatility_ratio = bb_width / avg_bb_width
                    except Exception:
                        # Keep default volatility_ratio = 1.0
                        pass
            except Exception:
                bb_width = 0.04  # 4% default width
                volatility_ratio = 1.0
            
            # Create MarketData object with validated values
            market_data = MarketData(
                price=current_price,
                rsi_5m=rsi_5m,
                rsi_15m=rsi_15m,
                rsi_1h=rsi_1h,
                volume=current_volume,
                volume_avg=volume_avg,
                bb_lower=bb_lower,
                bb_upper=bb_upper,
                bb_middle=bb_middle,
                ema_9_15m=ema_9_15m,
                ema_21_15m=ema_21_15m,
                ema_20_15m=ema_20_15m,
                ema_50_daily=ema_50_daily,
                weekly_support=weekly_support,
                btc_trend=btc_trend,
                macd_5m=macd_5m,
                macd_signal_5m=macd_signal_5m,
                macd_histogram_5m=macd_histogram_5m,
                stoch_k=stoch_k,
                stoch_d=stoch_d,
                atr_5m=atr_5m,
                volatility_ratio=volatility_ratio,
                btc_strength=btc_strength,
                timestamp=datetime.now()
            )
            
            # Log success for debugging
            self.log_message(f"Indicators calculated successfully", "success")
            return market_data
            
        except Exception as e:
            self.log_message(f"Critical error in indicator calculation: {str(e)[:100]}", "error")
            return None

    def check_strategy_conditions(self, data: MarketData) -> Dict[str, bool]:
        """OPTIMIZED v5: Adaptive strategy with market regime detection"""
        try:
            conditions = {}
            
            # ENHANCED: Advanced market regime detection
            is_volatile = data.volatility_ratio > 1.2
            is_trending = data.ema_9_15m > data.ema_21_15m  # Short-term trend
            is_range_bound = abs(data.price - data.ema_20_15m) / data.ema_20_15m < 0.01  # Price within 1% of EMA20
            
            # CORE CONDITION 1: Smart Bollinger Band Touch (ADAPTIVE)
            # Tighter BB requirement in trending markets, looser in volatile or ranging markets
            bb_threshold = 1.018 if is_volatile else 1.012 if is_range_bound else 1.005
            bb_touch_threshold = data.bb_lower * bb_threshold
            conditions['bb_touch'] = data.price <= bb_touch_threshold
            
            # CORE CONDITION 2: Dynamic RSI Oversold (ADAPTIVE)
            # More lenient in volatile markets, stricter in trending markets
            rsi_upper_threshold = 60 if is_volatile else 52 if is_range_bound else 48
            rsi_lower_threshold = 20 if is_volatile else 25  # Don't buy extreme oversold in stable markets
            conditions['rsi_oversold'] = data.rsi_5m < rsi_upper_threshold and data.rsi_5m > rsi_lower_threshold
            
            # CORE CONDITION 3: Enhanced MACD Momentum (MARKET ADAPTIVE)
            # Different MACD conditions for different market regimes
            macd_near_zero = abs(data.macd_5m) < data.atr_5m * 0.1  # MACD near zero relative to volatility
            # Fix: Previous histogram comparison was incorrect - ensure it's rising or near crossover
            prev_histogram = data.macd_histogram_5m * 0.8  # Simulate slightly lower previous value
            macd_rising = data.macd_histogram_5m > -0.0005 and data.macd_histogram_5m > prev_histogram  
            macd_positive_crossover = data.macd_5m > data.macd_signal_5m and data.macd_histogram_5m > 0
            
            if is_volatile:
                # In volatile markets, require stronger momentum signals
                conditions['macd_momentum'] = macd_positive_crossover or (macd_near_zero and macd_rising)
            else:
                # In stable markets, accept early momentum signals
                conditions['macd_momentum'] = macd_near_zero or macd_rising or macd_positive_crossover
            
            # CORE CONDITION 4: Precision Stochastic Recovery (FIXED)
            # Completely rewritten stochastic condition with 4 separate valid scenarios
            
            # Scenario 1: Deep oversold with any signs of life
            deep_oversold_recovery = data.stoch_k < 20 and data.stoch_k >= data.stoch_d * 0.95
            
            # Scenario 2: Regular oversold with clear recovery
            regular_oversold_recovery = data.stoch_k < 30 and (data.stoch_k >= data.stoch_d or data.stoch_k > data.stoch_d - 2)
            
            # Scenario 3: Early recovery momentum (K crossing above D)
            early_recovery = data.stoch_k < 40 and data.stoch_k > data.stoch_d
            
            # Scenario 4: Consolidation after oversold (K and D moving together under 40)
            consolidation_recovery = data.stoch_k < 40 and abs(data.stoch_k - data.stoch_d) < 2
            
            # Accept any valid recovery scenario
            conditions['stoch_recovery'] = (deep_oversold_recovery or 
                                           regular_oversold_recovery or 
                                           early_recovery or 
                                           consolidation_recovery)
            
            # CORE CONDITION 5: Multi-timeframe Trend Alignment (ENHANCED)
            # More sophisticated trend alignment that considers multiple timeframes
            price_above_ema = data.price > data.ema_20_15m * 0.995  # Price near or above EMA20
            price_support_bounce = data.price > data.weekly_support * 1.01 and data.rsi_15m > data.rsi_5m  # Bouncing from support
            higher_tf_uptrend = data.ema_50_daily < data.price * 1.05  # Daily trend not strongly bearish
            
            # Different trend requirements based on market regime
            if is_trending:
                # In trending markets, price should be above EMA
                conditions['trend_alignment'] = price_above_ema and higher_tf_uptrend
            else:
                # In ranging markets, accept support bounces
                conditions['trend_alignment'] = (price_above_ema or price_support_bounce) and higher_tf_uptrend
            
            # BONUS CONDITION 6: Smart Volume Profile (ENHANCED)
            # More sophisticated volume analysis
            declining_volume = data.volume < data.volume_avg * 0.8  # Accumulation
            expanding_volume = data.volume > data.volume_avg * 1.3  # Breakout
            
            # In volatile markets, we want expanding volume for confirmation
            # In ranging markets, declining volume can indicate accumulation
            if is_volatile:
                conditions['volume_confirm'] = expanding_volume
            else:
                conditions['volume_confirm'] = declining_volume or expanding_volume
            
            return conditions
        except Exception as e:
            self.log_message(f"Error in strategy conditions: {str(e)}", "error")
            return {
                'bb_touch': False, 
                'rsi_oversold': False, 
                'macd_momentum': False, 
                'stoch_recovery': False,
                'trend_alignment': False,
                'volume_confirm': False
            }

    def calculate_atr_levels(self, data: Dict[str, pd.DataFrame], entry_price: float) -> Dict[str, float]:
        """OPTIMIZED: Better ATR-based exit levels with dynamic reward:risk ratio"""
        try:
            if '5m' not in data or data['5m'] is None or len(data['5m']) < 14:
                # Not enough data, use percentage-based levels
                return {
                    'atr': entry_price * 0.01,
                    'stop_loss': entry_price * 0.985,  # 1.5% stop
                    'tp1': entry_price * 1.02,    # 2% TP1
                    'tp2': entry_price * 1.035,   # 3.5% TP2
                    'reward_risk_ratio': 1.33     # Default 2:1.5 ratio
                }
                
            df_5m = data['5m'].copy()
            
            # Calculate True Range
            df_5m['high_low'] = df_5m['high'] - df_5m['low']
            df_5m['high_close_prev'] = abs(df_5m['high'] - df_5m['close'].shift(1))
            df_5m['low_close_prev'] = abs(df_5m['low'] - df_5m['close'].shift(1))
            df_5m['true_range'] = df_5m[['high_low', 'high_close_prev', 'low_close_prev']].max(axis=1)
            
            # Remove NaN values
            df_5m = df_5m.dropna(subset=['true_range'])
            
            if len(df_5m) < 14:
                atr_14 = entry_price * 0.01  # Default to 1% if not enough data
            else:
                atr_14 = df_5m['true_range'].rolling(window=14).mean().iloc[-1]
                
                # NEW: Sanity check on ATR value - prevent extreme values
                atr_percent = atr_14 / entry_price * 100
                if atr_percent < 0.5 or atr_percent > 5:
                    # If ATR is outside reasonable range, use percentage fallback
                    atr_14 = entry_price * 0.01  # 1% of price
                    self.log_message(f"ATR outside reasonable range ({atr_percent:.2f}%), using default", "warning")
            
            # NEW: Dynamic ATR multipliers based on volatility
            # Calculate price volatility by measuring true range as percentage
            price_volatility = df_5m['true_range'].mean() / df_5m['close'].mean()
            volatility_factor = max(0.5, min(1.5, 1.0 / (price_volatility * 50))) if price_volatility > 0 else 1.0
            
            # Adjust multipliers based on volatility
            stop_multiplier = 0.8 * volatility_factor
            tp1_multiplier = 1.2 * volatility_factor
            tp2_multiplier = 2.0 * volatility_factor
            
            # Calculate stop loss using ATR - aim for consistent risk percentage
            stop_loss_raw = entry_price - (stop_multiplier * atr_14)
            stop_loss_percent = (entry_price - stop_loss_raw) / entry_price * 100
            
            # Ensure stop loss percentage is reasonable
            min_stop_percent = 0.7  # Minimum stop loss percentage
            max_stop_percent = 2.5  # Maximum stop loss percentage
            
            if stop_loss_percent < min_stop_percent:
                stop_loss = entry_price * (1 - min_stop_percent/100)
            elif stop_loss_percent > max_stop_percent:
                stop_loss = entry_price * (1 - max_stop_percent/100)
            else:
                stop_loss = stop_loss_raw
                
            # Calculate TP levels - with minimum reward:risk ratio
            tp1 = entry_price + (tp1_multiplier * atr_14)
            tp2 = entry_price + (tp2_multiplier * atr_14)
            
            # NEW: Ensure minimum reward:risk ratio of 1.5
            stop_distance = entry_price - stop_loss
            tp1_raw_distance = tp1 - entry_price
            min_tp1_distance = stop_distance * 1.5  # Minimum 1.5:1 reward:risk
            
            # If TP1 doesn't provide enough reward relative to risk, increase it
            if tp1_raw_distance < min_tp1_distance:
                tp1 = entry_price + min_tp1_distance
                tp2 = max(tp2, tp1 * 1.01)  # Ensure TP2 is above TP1
        
            # Ensure TPs are above entry and SL is below entry
            if tp1 <= entry_price:
                tp1 = entry_price * 1.02  # Fallback to 2%
                
            if tp2 <= tp1:
                tp2 = tp1 * 1.015  # At least 1.5% above TP1
                
            if stop_loss >= entry_price:
                stop_loss = entry_price * 0.985  # Fallback to 1.5% below
        
            # Calculate the reward:risk ratio
            tp1_profit = ((tp1 - entry_price) / entry_price) * 100
            stop_loss_risk = ((entry_price - stop_loss) / entry_price) * 100
            reward_risk_ratio = tp1_profit / stop_loss_risk if stop_loss_risk > 0 else 1.5
    
            return {
                'atr': atr_14,
                'stop_loss': stop_loss,
                'tp1': tp1,
                'tp2': tp2,
                'reward_risk_ratio': round(reward_risk_ratio, 2)
            }
        except Exception as e:
            self.log_message(f"ATR calculation error: {str(e)}", "warning")
            # Default percentage-based levels if ATR calculation fails
            return {
                'atr': entry_price * 0.01,
                'stop_loss': entry_price * 0.985,
                'tp1': entry_price * 1.02,
                'tp2': entry_price * 1.035,
                'reward_risk_ratio': 1.33
            }

    def check_entry_signals(self, symbol: str, data: MarketData, conditions: Dict[str, bool]) -> Optional[Dict]:
        """ENHANCED: Better signal quality filters with reward:risk validation"""
        
        try:
            # NEW: Check if any position is already open - stop scanning if we have one
            if len(self.position_manager.get_active_symbols()) > 0:
                # We already have an open position, don't generate new signals
                return None
                
            # Validation checks for critical indicators
            validation_errors = []
            
            if pd.isna(data.price) or data.price <= 0:
                validation_errors.append("Invalid price")
            if pd.isna(data.rsi_5m):
                validation_errors.append("Invalid RSI 5m")
            if pd.isna(data.stoch_k) or pd.isna(data.stoch_d):
                validation_errors.append("Invalid Stochastic")
            if pd.isna(data.macd_5m) or pd.isna(data.macd_signal_5m):
                validation_errors.append("Invalid MACD")
                
            if validation_errors:
                self.log_message(f"Entry validation failed for {symbol}: {', '.join(validation_errors)}", "warning")
                return None
                
            # Get core and bonus conditions
            core_conditions = ['bb_touch', 'rsi_oversold', 'macd_momentum', 'stoch_recovery', 'trend_alignment']
            bonus_conditions = ['volume_confirm']
            
            # Count conditions
            core_conditions_met = sum(conditions[cond] for cond in core_conditions)
            bonus_conditions_met = sum(conditions[cond] for cond in bonus_conditions)
            total_conditions_met = core_conditions_met + bonus_conditions_met
            
            # NEW: More advanced signal strength scoring (0-130 scale)
            score = 0
            
            # Base score from core conditions (most important)
            score += core_conditions_met * 20  # 0-100 from core conditions
            
            # Bonus points from extra conditions
            score += bonus_conditions_met * 10  # 0-10 from bonus condition
            
            # Bonus points for strong signals
            if conditions['bb_touch'] and data.price < data.bb_lower * 1.003:  # Very close to BB
                score += 10
            if conditions['stoch_recovery'] and data.stoch_k < 25:  # Very oversold
                score += 10
            if data.rsi_5m < 35:  # Very oversold RSI
                score += 10
            if data.macd_5m > data.macd_signal_5m and data.macd_histogram_5m > 0:  # Strong MACD
                score += 10
                
            # Minimum requirements - stronger requirements than before
            if core_conditions_met < 4 or score < 80:  # Need 4 core conditions AND a good score
                return None
            
            # Standard filters
            if symbol in self.position_manager.get_active_symbols():
                return None
                
            current_time = time.time()
            if symbol in self.last_alert_time and current_time - self.last_alert_time[symbol] < 180:
                return None
                
            # Modified: Only allow ONE position at a time (instead of config.MAX_CONCURRENT_POSITIONS)
            if len(self.position_manager.get_active_symbols()) >= 1:
                return None
            
            # Order book analysis for buying pressure
            imbalance_ratio = self.get_order_book_imbalance(symbol)
            if imbalance_ratio is None or imbalance_ratio < 1.1:
                return None
            
            # Dynamic entry level based on signal quality
            if score >= 120:  # Exceptional signal
                entry_level = 3
                confidence = 95
            elif score >= 100:  # Very strong signal
                entry_level = 2
                confidence = 85
            else:  # Good signal
                entry_level = 1
                confidence = 75
            
            # Boost confidence for extremely oversold conditions
            if data.stoch_k < 20:
                entry_level = min(3, entry_level + 1)
                confidence += 5
            
            if data.macd_5m > data.macd_signal_5m and data.macd_histogram_5m > 0:
                confidence += 5
                
            # Get fresh data for ATR levels
            market_data = self.get_binance_data(symbol)
            if not market_data or '5m' not in market_data:
                atr_levels = self.calculate_atr_levels({"5m": pd.DataFrame({
                    "high": [data.price * 1.01], "low": [data.price * 0.99], "close": [data.price]
                })}, data.price)
            else:
                atr_levels = self.calculate_atr_levels(market_data, data.price)

            # Get reward:risk ratio
            reward_risk_ratio = atr_levels.get('reward_risk_ratio', 1.33)
            
            # NEW: Reject trades with poor reward:risk ratio
            if reward_risk_ratio < 1.2:
                self.log_message(f"Rejected {symbol} - Poor R:R ratio: {reward_risk_ratio}", "warning")
                return None

            # Ensure take profit and stop loss levels are valid
            if pd.isna(atr_levels['tp1']) or pd.isna(atr_levels['tp2']) or pd.isna(atr_levels['stop_loss']):
                self.log_message(f"Invalid ATR levels for {symbol}, using percentage-based levels", "warning")
                atr_levels = {
                    'atr': data.price * 0.01,
                    'stop_loss': data.price * 0.985,
                    'tp1': data.price * 1.02,
                    'tp2': data.price * 1.035,
                    'reward_risk_ratio': 1.33
                }
            
            # Ensure TP > Entry > SL
            if atr_levels['tp1'] <= data.price or atr_levels['tp2'] <= data.price or atr_levels['stop_loss'] >= data.price:
                self.log_message(f"TP/SL calculation error for {symbol}, fixing levels", "warning")
                atr_levels['stop_loss'] = min(atr_levels['stop_loss'], data.price * 0.985)
                atr_levels['tp1'] = max(atr_levels['tp1'], data.price * 1.02)
                atr_levels['tp2'] = max(atr_levels['tp2'], data.price * 1.035)
            
            signal = {
                'type': 'LONG_ENTRY',
                'symbol': symbol,
                'coin': symbol.replace('USDT', ''),
                'entry_price': data.price,
                'tp1': atr_levels['tp1'],
                'tp2': atr_levels['tp2'],
                'stop_loss': atr_levels['stop_loss'],
                'entry_level': entry_level,
                'confidence': min(confidence, 99),
                'signal_strength': score,  # NEW: Use the score instead of condition count
                'core_conditions_met': core_conditions_met,
                'total_conditions_met': total_conditions_met,
                'rsi_5m': data.rsi_5m,
                'rsi_15m': data.rsi_15m,
                'rsi_1h': data.rsi_1h,
                'macd_momentum': data.macd_histogram_5m,
                'stoch_k': data.stoch_k,
                'volatility_ratio': data.volatility_ratio,
                'reward_risk_ratio': reward_risk_ratio,  # Include R:R ratio
                'timestamp': datetime.now().isoformat(),
                'atr_value': atr_levels['atr'],
                'order_book_imbalance': imbalance_ratio,
                'strategy_version': 'v5_adaptive'  # Updated strategy version
            }
            
            # Process signal
            if self.telegram_notifier:
                telegram_success = self.telegram_notifier.send_signal_alert(signal)
                if not telegram_success:
                    self.log_message(f"Warning: Telegram notification failed for {symbol}", "warning")
        
            position_success = self.position_manager.add_position(signal)
            
            if position_success:
                self.last_alert_time[symbol] = current_time
                self.log_message(f"SIGNAL: {symbol} LONG ENTRY - Level {signal['entry_level']} (Score: {score}, R:R: {reward_risk_ratio})", "success")
                
                try:
                    with open('signals.json', 'a') as f:
                        f.write(json.dumps(signal) + '\n')
                except Exception as e:
                    self.log_message(f"Error saving signal: {str(e)[:30]}", "error")
                    
                return signal
            else:
                self.log_message(f"Failed to open position for {symbol}", "error")
                return None
                
        except Exception as e:
            self.log_message(f"Error in entry signal processing for {symbol}: {str(e)[:100]}", "error")
            return None

    # Add a method to start the bot
    def start(self):
        """Start the bot and send notification"""
        self.running = True
        self.log_message("✅ Bot started successfully", "success")
        
        # Send Telegram notification that bot has started
        if self.telegram_notifier:
            self.telegram_notifier.send_bot_status_update(
                "ONLINE", 
                "The trading bot has been started successfully.\n\nNow scanning for trading signals..."
            )
    
    def stop(self):
        """Stop the bot and send notification"""
        self.running = False
        self.log_message("🛑 Bot stopped", "warning")
        
        # Send Telegram notification that bot has stopped
        if self.telegram_notifier:
            self.telegram_notifier.send_bot_status_update(
                "OFFLINE", 
                "The trading bot has been stopped."
            )
    
    def start_scanning(self):
        """Start the scanning process in a separate thread"""
        if not hasattr(self, 'scan_thread') or not self.scan_thread.is_alive():
            self.scan_thread = threading.Thread(target=self.scanning_loop, daemon=True)
            self.scan_thread.start()
            self.log_message("🔍 Scanner thread started", "success")
    
    def scanning_loop(self):
        """Main scanning loop that runs continuously while the bot is running"""
        self.log_message("🔄 Starting scanning loop...", "info")
        
        while self.running:
            try:
                # Skip scanning if we have an open position
                if len(self.position_manager.get_active_symbols()) > 0:
                    self.log_message("⏸️ Position active, pausing scanner", "info")
                    time.sleep(config.SCAN_INTERVAL)
                    continue
                    
                # Fetch top gainers
                self.top_gainers = self.get_top_gainers()
                if not self.top_gainers:
                    self.log_message("⚠️ Failed to get gainers, retrying...", "warning")
                    time.sleep(config.SCAN_INTERVAL)
                    continue
                    
                # Extract symbols
                self.scanning_symbols = [gainer['symbol'] for gainer in self.top_gainers]
                
                # Scan each symbol
                for symbol in self.scanning_symbols:
                    if not self.running:
                        break
                        
                    try:
                        self.current_scanning_symbol = symbol.replace('USDT', '')
                        
                        # Get market data
                        market_data = self.get_binance_data(symbol)
                        if not market_data:
                            continue
                            
                        # Calculate indicators
                        data = self.calculate_indicators(market_data)
                        if not data:
                            continue
                            
                        # Store data
                        self.current_data[symbol] = data
                        
                        # Check signals
                        conditions = self.check_strategy_conditions(data)
                        signal = self.check_entry_signals(symbol, data, conditions)
                        
                        if signal:
                            self.scan_stats['signals_found'] += 1
                            
                        # Update scan stats
                        self.scan_stats['total_scanned'] += 1
                        
                        # Delay between checks to avoid rate limits
                        time.sleep(1)
                        
                    except Exception as e:
                        self.log_message(f"Error scanning {symbol}: {str(e)[:50]}", "error")
                        continue
                
                # Scan cycle complete
                self.current_scanning_symbol = None
                self.scan_stats['scan_cycles'] += 1
                self.scan_stats['last_scan_time'] = datetime.now()
                self.log_message(f"✅ Scan cycle #{self.scan_stats['scan_cycles']} complete", "success")
                
                # Wait before starting next cycle
                time.sleep(config.SCAN_INTERVAL)
                
            except Exception as e:
                self.log_message(f"❌ Scanning error: {str(e)[:100]}", "error")
                time.sleep(config.SCAN_INTERVAL)
                
        self.log_message("🛑 Scanner loop stopped", "warning")

def main():
    """Main function to run the terminal app"""
    # Clear screen and hide cursor
    os.system('clear' if os.name == 'posix' else 'cls')
    
    bot = CryptoSignalBot()
    
    # Start the bot
    bot.start()
    
    # Start the scanning process
    bot.start_scanning()
    
    try:
        with Live(bot.render_dashboard(), refresh_per_second=2, screen=True) as live:
            while True:
                live.update(bot.render_dashboard())
                time.sleep(0.5)
                
    except KeyboardInterrupt:
        bot.stop()
        bot.console.print("\n[red]Bot stopped by user[/red]")
        sys.exit(0)

if __name__ == '__main__':
    main()