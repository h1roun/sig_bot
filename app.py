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
        table.add_column("Status", style="white", width=6)
        
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
                    else:
                        volume_str = "Wait"  # Change "N/A" to "Wait" for clarity
                    
                    # Better error handling for RSI
                    if hasattr(data, 'rsi_5m') and not pd.isna(data.rsi_5m):
                        rsi_str = f"{data.rsi_5m:.0f}"
                    else:
                        rsi_str = "Wait"  # Change "N/A" to "Wait" for clarity
                except Exception as e:
                    # Handle any unexpected errors in condition checking
                    self.log_message(f"Error processing {symbol}: {str(e)[:20]}", "error")
                    core_conditions_met = 0
                    volume_str = "Err"  # Error indicator
                    rsi_str = "Err"  # Error indicator
            else:
                core_conditions_met = 0
                volume_str = "Scan"  # Clearer indication that scan is pending
                rsi_str = "Scan"  # Clearer indication that scan is pending
            
            change_style = "green" if gainer['change_24h'] > 0 else "red"
            conditions_style = "green" if core_conditions_met >= 4 else "yellow" if core_conditions_met >= 3 else "white"
            
            if symbol == f"{self.current_scanning_symbol}USDT":
                status = "SCAN"
                status_style = "yellow"
            elif core_conditions_met >= 4:
                status = "READY"
                status_style = "red"
            elif core_conditions_met >= 3:
                status = "Near"
                status_style = "yellow"
            else:
                status = "Watch"
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
        """Updated conditions panel for new 5-condition strategy"""
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
                
                if core_conditions_met > 0:
                    top_coins.append({
                        'coin': gainer['coin'],
                        'symbol': symbol,
                        'core_conditions_met': core_conditions_met,
                        'total_conditions': total_conditions,
                        'conditions': conditions,
                        'data': data,
                        'price': gainer['price'],
                        'change': gainer['change_24h']
                    })
        
        # Sort by core conditions met, then total conditions
        top_coins.sort(key=lambda x: (x['core_conditions_met'], x['total_conditions']), reverse=True)
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
            
            # Create detailed table for this coin
            coin_table = Table(
                title=f"{coin_info['coin']} - {coin_info['core_conditions_met']}/5 Core ({coin_info['total_conditions']}/6 Total)", 
                box=box.SIMPLE, 
                title_style="bold green" if coin_info['core_conditions_met'] >= 4 else "bold yellow" if coin_info['core_conditions_met'] >= 3 else "cyan"
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
            
            # 6. Volume Confirm (BONUS)
            volume_style = "green" if conditions['volume_confirm'] else "yellow"
            volume_ratio = data.volume / data.volume_avg
            coin_table.add_row(
                "Volume",
                Text("✓" if conditions['volume_confirm'] else "○", style=volume_style),
                f"{volume_ratio:.2f}x",
                "<0.8 or >1.3"
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
        
        return Panel(layout, title="5-Core Strategy (*=Required, 4/5 needed)", style="green" if top_3_coins and top_3_coins[0]['core_conditions_met'] >= 4 else "white")

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
    
        return data

    def calculate_indicators(self, data: Dict[str, pd.DataFrame]) -> Optional[MarketData]:
        """Calculate all indicators with robust error handling to prevent N/A values"""
        required_intervals = ["5m", "15m", "1h", "1d"]
        
        # Check if we have all required intervals
        if not all(interval in data for interval in required_intervals):
            missing = [i for i in required_intervals if i not in data]
            self.log_message(f"Missing intervals: {missing}", "warning")
            return None
            
        # Check if dataframes have enough data
        for interval in required_intervals:
            if interval not in data or len(data[interval]) < 50:  # Fixed: Check if interval exists first
                self.log_message(f"Not enough data for {interval}", "warning")
                return None
        
        try:
            current_price = float(data['5m']['close'].iloc[-1])
            
            # Existing RSI indicators
            rsi_5m = ta.momentum.RSIIndicator(data['5m']['close'], window=7).rsi().iloc[-1]
            rsi_15m = ta.momentum.RSIIndicator(data['15m']['close'], window=7).rsi().iloc[-1]
            rsi_1h = ta.momentum.RSIIndicator(data['1h']['close'], window=14).rsi().iloc[-1]
            
            # Check for NaN values in critical indicators
            if pd.isna(rsi_5m) or pd.isna(rsi_15m) or pd.isna(rsi_1h):
                self.log_message(f"Invalid RSI values detected", "warning")
                return None
            
            # Enhanced Bollinger Bands
            bb_5m = ta.volatility.BollingerBands(data['5m']['close'], window=20, window_dev=2)
            bb_lower = bb_5m.bollinger_lband().iloc[-1]
            bb_upper = bb_5m.bollinger_hband().iloc[-1]
            bb_middle = bb_5m.bollinger_mavg().iloc[-1]
            
            # Check for NaN values in Bollinger bands
            if pd.isna(bb_lower) or pd.isna(bb_upper) or pd.isna(bb_middle):
                self.log_message(f"Invalid Bollinger Band values", "warning")
                return None
            
            # EMA indicators
            ema_9_15m = ta.trend.EMAIndicator(data['15m']['close'], window=9).ema_indicator().iloc[-1]
            ema_21_15m = ta.trend.EMAIndicator(data['15m']['close'], window=21).ema_indicator().iloc[-1]
            ema_20_15m = ta.trend.EMAIndicator(data['15m']['close'], window=20).ema_indicator().iloc[-1]
            ema_50_daily = ta.trend.EMAIndicator(data['1d']['close'], window=50).ema_indicator().iloc[-1]
            
            # Check for NaN in EMAs
            if pd.isna(ema_9_15m) or pd.isna(ema_21_15m) or pd.isna(ema_20_15m) or pd.isna(ema_50_daily):
                self.log_message(f"Invalid EMA values", "warning")
                return None
            
            # NEW: MACD for momentum confirmation
            macd_indicator = ta.trend.MACD(data['5m']['close'], window_slow=26, window_fast=12, window_sign=9)
            macd_5m = macd_indicator.macd().iloc[-1]
            macd_signal_5m = macd_indicator.macd_signal().iloc[-1]
            macd_histogram_5m = macd_indicator.macd_diff().iloc[-1]
            
            # Check for NaN in MACD
            if pd.isna(macd_5m) or pd.isna(macd_signal_5m) or pd.isna(macd_histogram_5m):
                self.log_message(f"Invalid MACD values", "warning")
                return None
            
            # NEW: Stochastic for oversold confirmation
            stoch_indicator = ta.momentum.StochasticOscillator(data['5m']['high'], data['5m']['low'], data['5m']['close'], window=14, smooth_window=3)
            stoch_k = stoch_indicator.stoch().iloc[-1]
            stoch_d = stoch_indicator.stoch_signal().iloc[-1]
            
            # Check for NaN in stochastic
            if pd.isna(stoch_k) or pd.isna(stoch_d):
                self.log_message(f"Invalid Stochastic values", "warning")
                return None
            
            # NEW: ATR for volatility
            atr_indicator = ta.volatility.AverageTrueRange(data['5m']['high'], data['5m']['low'], data['5m']['close'], window=14)
            atr_5m = atr_indicator.average_true_range().iloc[-1]
            
            if pd.isna(atr_5m):
                self.log_message(f"Invalid ATR values", "warning")
                return None
            
            # Volume analysis - prevent division by zero
            current_volume = float(data['5m']['volume'].iloc[-1])
            volume_avg = data['5m']['volume'].rolling(20).mean().iloc[-1]
            
            # Ensure volume_avg is not zero to prevent division errors
            if pd.isna(volume_avg) or volume_avg <= 0:
                volume_avg = 1.0  # Set to 1 to prevent division by zero
            
            # Support level
            weekly_support = data['1d']['low'].tail(7).min()
            
            # NEW: Enhanced BTC trend strength
            price_vs_ema50 = (current_price - ema_50_daily) / ema_50_daily * 100
            btc_trend = "UP" if price_vs_ema50 > -2 else "DOWN"  # More lenient
            btc_strength = abs(price_vs_ema50)
            
            # NEW: Volatility ratio for market regime with safeguards
            bb_width = (bb_upper - bb_lower) / bb_middle if bb_middle > 0 else 0
            historical_bb_width = []
            for i in range(20):
                try:
                    hist_bb = ta.volatility.BollingerBands(data['5m']['close'].iloc[-(20-i):], window=20, window_dev=2)
                    hist_upper = hist_bb.bollinger_hband().iloc[-1]
                    hist_lower = hist_bb.bollinger_lband().iloc[-1]
                    hist_middle = hist_bb.bollinger_mavg().iloc[-1]
                    
                    if not pd.isna(hist_upper) and not pd.isna(hist_lower) and not pd.isna(hist_middle) and hist_middle > 0:
                        hist_width = (hist_upper - hist_lower) / hist_middle
                        historical_bb_width.append(hist_width)
                except Exception:
                    continue
        
            if len(historical_bb_width) > 0:
                avg_bb_width = sum(historical_bb_width) / len(historical_bb_width)
            else:
                avg_bb_width = bb_width if bb_width > 0 else 1.0
                
            # Prevent division by zero with safeguard
            volatility_ratio = bb_width / avg_bb_width if avg_bb_width > 0 else 1.0
            
            return MarketData(
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
        except Exception as e:
            self.log_message(f"Error calculating indicators: {str(e)[:50]}", "error")
            return None

    def get_order_book_imbalance(self, symbol: str) -> Optional[float]:
        """Get order book imbalance ratio with better error handling"""
        try:
            url = "https://api.binance.com/api/v3/depth"
            params = {'symbol': symbol, 'limit': 100}
            response = requests.get(url, params=params, timeout=5)
            
            if response.status_code == 200:
                depth_data = response.json()
                
                # Safety checks for empty order book
                if not depth_data.get('bids') or not depth_data.get('asks'):
                    return None
                    
                total_bid_volume = sum(float(bid[1]) for bid in depth_data['bids'])
                total_ask_volume = sum(float(ask[1]) for ask in depth_data['asks'])
                
                if total_ask_volume > 0:
                    return total_bid_volume / total_ask_volume
                else:
                    return 2.0  # Return a high value when there are no asks
            return None
        except Exception as e:
            self.log_message(f"Order book error: {str(e)[:20]}", "error")
            return None

    def calculate_atr_levels(self, data: Dict[str, pd.DataFrame], entry_price: float) -> Dict[str, float]:
        """Calculate ATR-based levels with safeguards for extreme values"""
        try:
            df_5m = data['5m'].copy()
            
            # Calculate True Range
            df_5m['high_low'] = df_5m['high'] - df_5m['low']
            df_5m['high_close_prev'] = abs(df_5m['high'] - df_5m['close'].shift(1))
            df_5m['low_close_prev'] = abs(df_5m['low'] - df_5m['close'].shift(1))
            df_5m['true_range'] = df_5m[['high_low', 'high_close_prev', 'low_close_prev']].max(axis=1)
            
            # Calculate ATR
            atr_14 = df_5m['true_range'].rolling(window=14).mean().iloc[-1]
            
            # Add safeguards for extreme values
            min_stop_percent = 0.7  # Minimum stop loss percentage
            max_stop_percent = 2.5  # Maximum stop loss percentage
            
            # Calculate stop loss using ATR
            stop_loss_raw = entry_price - (0.8 * atr_14)
            stop_loss_percent = (entry_price - stop_loss_raw) / entry_price * 100
            
            # Ensure stop loss is within reasonable range
            if stop_loss_percent < min_stop_percent:
                stop_loss = entry_price * (1 - min_stop_percent/100)
            elif stop_loss_percent > max_stop_percent:
                stop_loss = entry_price * (1 - max_stop_percent/100)
            else:
                stop_loss = stop_loss_raw
                
            # Calculate reasonable TP levels
            tp1 = entry_price + (1.0 * atr_14)
            tp2 = entry_price + (1.8 * atr_14)
            
            return {
                'atr': atr_14,
                'stop_loss': stop_loss,
                'tp1': tp1,
                'tp2': tp2
            }
        except Exception as e:
            self.log_message(f"ATR calculation error: {str(e)[:30]}", "warning")
            # Default percentage-based levels if ATR calculation fails
            return {
                'atr': entry_price * 0.01,  # Estimate ATR as 1% of price
                'stop_loss': entry_price * 0.985,  # 1.5% stop loss
                'tp1': entry_price * 1.02,  # 2% TP1
                'tp2': entry_price * 1.035   # 3.5% TP2
            }

    def check_strategy_conditions(self, data: MarketData) -> Dict[str, bool]:
        """OPTIMIZED: Check only 5 CORE conditions with adaptive thresholds"""
        try:
            conditions = {}
            
            # Adaptive thresholds based on volatility
            high_vol = data.volatility_ratio > 1.2
            bb_threshold = 1.015 if high_vol else 1.008  # More lenient in high volatility
            rsi_threshold = 55 if high_vol else 50       # More lenient RSI in high volatility
            
            # CORE CONDITION 1: Bollinger Band Touch (ADAPTIVE)
            bb_touch_threshold = data.bb_lower * bb_threshold
            conditions['bb_touch'] = data.price <= bb_touch_threshold
            
            # CORE CONDITION 2: RSI Oversold but not extreme (ADAPTIVE)
            conditions['rsi_oversold'] = data.rsi_5m < rsi_threshold and data.rsi_5m > 25
            
            # CORE CONDITION 3: MACD Momentum Building (FIXED)
            # Check for MACD momentum - either rising histogram OR positive crossover
            # Using "near zero and not deeply negative" is more reliable than just > -0.001
            macd_near_crossover = data.macd_histogram_5m > -0.002 and data.macd_histogram_5m < 0.002
            macd_positive_crossover = data.macd_5m > data.macd_signal_5m and data.macd_histogram_5m > 0
            conditions['macd_momentum'] = macd_near_crossover or macd_positive_crossover
            
            # CORE CONDITION 4: Stochastic Oversold Recovery (FIXED FOR REAL)
            # More forgiving conditions for < 40 stochastic values
            # Deep oversold (below 20) - any sign of life is good
            stoch_deep_oversold = data.stoch_k < 20 and (data.stoch_k >= data.stoch_d * 0.95)
            
            # Regular oversold (below 30) - allow more flexibility
            # Fix the logic error: was comparing stoch_k with itself minus 2
            stoch_oversold = data.stoch_k < 30 and (data.stoch_k >= data.stoch_d * 0.97 or data.stoch_k > data.stoch_d - 2)
            
            # Between 30-40 - recovery or at least not declining
            stoch_low = data.stoch_k < 40 and data.stoch_k >= 30 and (data.stoch_k >= data.stoch_d * 0.99)
            
            # Stochastic momentum - either flattening or rising
            stoch_rising = abs(data.stoch_k - data.stoch_d) < 3 and data.stoch_k < 40
            
            # Accept any of these conditions
            conditions['stoch_recovery'] = stoch_deep_oversold or stoch_oversold or stoch_low or stoch_rising
            
            # CORE CONDITION 5: Trend Alignment (FIXED)
            # Clearer check: Either price above/near EMA20 OR price showing strong recovery from support
            near_ema = data.price > data.ema_20_15m * 0.996  # Price near or above EMA20
            support_bounce = data.price > data.weekly_support * 1.01 and data.price < data.ema_20_15m * 0.99 and data.rsi_15m > 40
            trend_ok = near_ema or support_bounce
            conditions['trend_alignment'] = trend_ok
            
            # BONUS CONDITION 6: Volume Confirmation (OPTIONAL - not required)
            # Either declining volume (accumulation) OR increasing volume (breakout)
            volume_ratio = data.volume / data.volume_avg if data.volume_avg > 0 else 1.0  # Prevent division by zero
            conditions['volume_confirm'] = (volume_ratio < 0.8) or (volume_ratio > 1.3)
            
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

    def check_entry_signals(self, symbol: str, data: MarketData, conditions: Dict[str, bool]) -> Optional[Dict]:
        """OPTIMIZED: More lenient entry requirements"""
        
        # NEW REQUIREMENT: At least 4 out of 5 CORE conditions (instead of all 8)
        core_conditions = ['bb_touch', 'rsi_oversold', 'macd_momentum', 'stoch_recovery', 'trend_alignment']
        core_conditions_met = sum(conditions[cond] for cond in core_conditions)
        
        if core_conditions_met < 4:
            return None
        
        # FILTER 1: No duplicate positions
        if symbol in self.position_manager.get_active_symbols():
            return None
            
        # FILTER 2: Reduced cooldown (3 minutes instead of 5)
        current_time = time.time()
        if symbol in self.last_alert_time and current_time - self.last_alert_time[symbol] < 180:
            return None
            
        # FILTER 3: Maximum concurrent positions
        if len(self.position_manager.get_active_symbols()) >= config.MAX_CONCURRENT_POSITIONS:
            return None
        
        # FILTER 4: RELAXED order book requirement (1.1 instead of 1.3)
        imbalance_ratio = self.get_order_book_imbalance(symbol)
        if imbalance_ratio is None or imbalance_ratio < 1.1:
            return None

        # ENHANCED: Entry level based on signal strength
        signal_strength = core_conditions_met + (1 if conditions.get('volume_confirm', False) else 0)
        
        if signal_strength >= 6:  # Perfect signal
            entry_level = 3
            confidence = 95
        elif signal_strength == 5:  # Strong signal
            entry_level = 2
            confidence = 85
        else:  # Good signal (4 conditions)
            entry_level = 1
            confidence = 75
        
        # Additional strength factors
        if data.stoch_k < 20:  # Very oversold
            entry_level = min(3, entry_level + 1)
            confidence += 5
        
        if data.macd_5m > data.macd_signal_5m and data.macd_histogram_5m > 0:  # Strong momentum
            confidence += 5
            
        market_data = self.get_binance_data(symbol)
        if not market_data or '5m' not in market_data:
            return None
        
        atr_levels = self.calculate_atr_levels(market_data, data.price)
        
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
            'signal_strength': signal_strength,
            'core_conditions_met': core_conditions_met,
            'rsi_5m': data.rsi_5m,
            'rsi_15m': data.rsi_15m,
            'rsi_1h': data.rsi_1h,
            'macd_momentum': data.macd_histogram_5m,
            'stoch_k': data.stoch_k,
            'volatility_ratio': data.volatility_ratio,
            'timestamp': datetime.now().isoformat(),
            'atr_value': atr_levels['atr'],
            'order_book_imbalance': imbalance_ratio,
            'strategy_version': 'v4_optimized'
        }
        
        self.position_manager.add_position(signal)
        
        if self.telegram_notifier:
            self.telegram_notifier.send_signal_alert(signal)
        
        self.last_alert_time[symbol] = current_time
        return signal

    def run_scanner(self):
        """Main scanning loop with better error logging and recovery"""
        while self.running:
            try:
                self.log_message("Fetching top 35 gainers...", "info")
                self.top_gainers = self.get_top_gainers()
                self.scanning_symbols = [coin['symbol'] for coin in self.top_gainers[:35]]  # Scan 35 coins
                
                if not self.scanning_symbols:
                    self.log_message("No symbols to scan", "warning")
                    time.sleep(30)
                    continue
                
                active_positions = self.position_manager.get_active_symbols()
                available_symbols = [s for s in self.scanning_symbols if s not in active_positions]
                
                signals_found = 0
                scanned_count = 0
                error_count = 0  # Track errors for logging
                
                # Don't clear all data, just mark as stale
                for symbol in self.current_data.keys():
                    if symbol not in available_symbols:
                        self.current_data[symbol] = None
            
                self.log_message(f"Starting scan of {len(available_symbols)} coins", "info")
                
                for i, symbol in enumerate(available_symbols):
                    try:
                        self.current_scanning_symbol = symbol.replace('USDT', '')
                        
                        # Update progress in stats
                        self.scan_stats['total_scanned'] = scanned_count
                        
                        market_data = self.get_binance_data(symbol)
                        if not market_data or '5m' not in market_data:
                            self.log_message(f"No market data for {symbol}", "warning")
                            self.current_data[symbol] = None
                            error_count += 1
                            continue
                            
                        current_data = self.calculate_indicators(market_data)
                        if not current_data:
                            self.log_message(f"Failed to calculate indicators for {symbol}", "warning")
                            self.current_data[symbol] = None
                            error_count += 1
                            continue
                        
                        self.current_data[symbol] = current_data
                        scanned_count += 1
                        
                        conditions = self.check_strategy_conditions(current_data)
                        conditions_met = sum(conditions.values())
                        
                        # Log progress every 10 coins
                        if scanned_count % 10 == 0:
                            self.log_message(f"Scanned {scanned_count}/{len(available_symbols)} coins", "info")
                        
                        signal = self.check_entry_signals(symbol, current_data, conditions)
                        
                        if signal:
                            signals_found += 1
                            coin_name = symbol.replace('USDT', '')
                            self.log_message(f"SIGNAL: {coin_name} LONG ENTRY - Level {signal['entry_level']}", "success")
                            
                            with open('signals.json', 'a') as f:
                                f.write(json.dumps(signal) + '\n')
                        
                        time.sleep(0.2)
                        
                    except Exception as e:
                        self.log_message(f"Error scanning {symbol}: {str(e)[:40]}", "error")
                        self.current_data[symbol] = None
                        error_count += 1
                        continue
                
                # Complete scan cycle with detailed stats
                self.current_scanning_symbol = None
                self.scan_stats['scan_cycles'] += 1
                self.scan_stats['total_scanned'] = scanned_count
                self.scan_stats['signals_found'] += signals_found
                self.scan_stats['last_scan_time'] = datetime.now()
                
                # Log summary with error count
                if signals_found > 0:
                    self.log_message(f"Scan complete: {signals_found} signals, {scanned_count} OK, {error_count} errors", "success")
                else:
                    self.log_message(f"Scan complete: {scanned_count} OK, {error_count} errors, no signals", "info")
                
                time.sleep(12)
                
            except Exception as e:
                self.log_message(f"Critical error during scan: {str(e)}", "error")
                time.sleep(30)  # Wait longer after critical errors
            
          

    def start(self):
        """Start the bot"""
        if not self.running:
            self.running = True
            scanner_thread = threading.Thread(target=self.run_scanner, daemon=True)
            scanner_thread.start()
            self.log_message("Multi-Scanner Started - Terminal Edition", "success")

    def stop(self):
        """Stop the bot"""
        self.running = False
        self.position_manager.stop_monitoring()
        self.log_message("Bot Stopped", "warning")

def main():
    """Main function to run the terminal app"""
    # Clear screen and hide cursor
    os.system('clear' if os.name == 'posix' else 'cls')
    
    bot = CryptoSignalBot()
    
    # Start the bot
    bot.start()
    
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