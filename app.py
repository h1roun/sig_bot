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
        """Create top gainers panel with improved data validation and error handling"""
        table = Table(title="Top 35 Gainers", box=box.SIMPLE)
        table.add_column("Coin", style="cyan", width=4)
        table.add_column("Price", style="white", width=7)
        table.add_column("Chg%", style="white", width=5)
        table.add_column("Core", style="white", width=4)  
        table.add_column("Vol", style="white", width=5)
        table.add_column("RSI", style="white", width=4)
        table.add_column("Status", style="white", width=6)
        
        display_gainers = self.top_gainers[:35]
        
        for gainer in display_gainers:
            symbol = gainer['symbol']
            data = self.current_data.get(symbol)
            
            # Default values in case data is missing
            core_conditions_met = 0
            volume_str = "..."
            rsi_str = "..."
            status = "Watch"
            status_style = "white"
            
            try:
                if data and hasattr(data, 'rsi_5m') and hasattr(data, 'volume') and hasattr(data, 'volume_avg'):
                    # Safely calculate conditions
                    conditions = self.check_strategy_conditions(data)
                    core_conditions = ['bb_touch', 'rsi_oversold', 'macd_momentum', 'stoch_recovery', 'trend_alignment']
                    core_conditions_met = sum(conditions[cond] for cond in core_conditions)
                    
                    # Safe volume calculation
                    if hasattr(data, 'volume') and hasattr(data, 'volume_avg') and data.volume_avg > 0:
                        volume_str = f"{data.volume/data.volume_avg:.1f}x"
                    else:
                        volume_str = "0.0x"
                        
                    # Safe RSI calculation
                    if hasattr(data, 'rsi_5m') and not pd.isna(data.rsi_5m):
                        rsi_str = f"{data.rsi_5m:.0f}"
                    else:
                        rsi_str = "50"
                        
                    # Status determination
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
                else:
                    # Mark as scanning if this is the current symbol
                    if symbol == f"{self.current_scanning_symbol}USDT":
                        volume_str = "..."
                        rsi_str = "..."
                        status = "SCAN"
                        status_style = "yellow"
            except Exception as e:
                # Fallback if any calculation fails
                self.log_message(f"Error processing {symbol}: {str(e)[:20]}", "error")
            
            change_style = "green" if gainer['change_24h'] > 0 else "red"
            conditions_style = "green" if core_conditions_met >= 4 else "yellow" if core_conditions_met >= 3 else "white"
            
            table.add_row(
                gainer['coin'][:4],
                f"${gainer['price']:.3f}",
                Text(f"{gainer['change_24h']:+.1f}", style=change_style),
                Text(f"{core_conditions_met}/5", style=conditions_style),
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
                f"{data.stoch_k:.1f}",
                "< 40"
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
                conditions_met = sum(conditions.values())
                footer_text.append(f"Scanning: {self.current_scanning_symbol} ({conditions_met}/8) | ", style="yellow")
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
        """Fetch real-time data from Binance API with retry logic"""
        base_url = "https://api.binance.com/api/v3/klines"
        data = {}
        max_retries = 3
        
        if not symbol:
            return {}
        
        for interval in intervals:
            retries = 0
            while retries < max_retries:
                try:
                    params = {
                        'symbol': symbol,
                        'interval': interval,
                        'limit': 200
                    }
                    response = requests.get(base_url, params=params, timeout=10)
                    if response.status_code == 200:
                        klines = response.json()
                        
                        # Check if we have enough data
                        if len(klines) < 50:
                            self.log_message(f"Not enough {interval} data for {symbol}: only {len(klines)} candles", "warning")
                            retries += 1
                            time.sleep(0.5)
                            continue
                        
                        df = pd.DataFrame(klines, columns=[
                            'timestamp', 'open', 'high', 'low', 'close', 'volume',
                            'close_time', 'quote_asset_volume', 'number_of_trades',
                            'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
                        ])
                        
                        # Convert all price columns to numeric to avoid errors
                        for col in ['open', 'high', 'low', 'close', 'volume']:
                            df[col] = pd.to_numeric(df[col], errors='coerce')
                        
                        # Verify that there are no NaN values in critical columns
                        if df['close'].isna().any() or df['volume'].isna().any():
                            self.log_message(f"NaN values in {interval} data for {symbol}", "warning")
                            retries += 1
                            time.sleep(0.5)
                            continue
                        
                        data[interval] = df
                        break
                    else:
                        self.log_message(f"Error fetching {interval} data for {symbol}: {response.status_code}", "error")
                        retries += 1
                        time.sleep(1)  # Exponential backoff
                except Exception as e:
                    self.log_message(f"Exception fetching {interval} data for {symbol}: {str(e)[:30]}", "error")
                    retries += 1
                    time.sleep(1)
    
    # Check if we have all required intervals
    for interval in intervals:
        if interval not in data:
            return {}  # Missing a required interval
            
    return data

def calculate_indicators(self, data: Dict[str, pd.DataFrame]) -> Optional[MarketData]:
    """Calculate all technical indicators with comprehensive error handling and fallbacks"""
    try:
        # Validate input data first
        required_intervals = ['5m', '15m', '1h', '1d']
        for interval in required_intervals:
            if interval not in data or data[interval].empty:
                return None
            
            # Make sure we have enough data points for calculations
            if len(data[interval]) < 50:
                self.log_message(f"Not enough data points for {interval}", "warning")
                return None
        
        # Extract price and ensure it's valid
        try:
            current_price = float(data['5m']['close'].iloc[-1])
            if pd.isna(current_price) or current_price <= 0:
                return None
        except Exception as e:
            self.log_message(f"Error extracting price: {str(e)[:30]}", "error")
            return None
        
        # Initialize with default values in case calculations fail
        indicator_values = {
            'rsi_5m': 50.0,
            'rsi_15m': 50.0,
            'rsi_1h': 50.0,
            'bb_lower': current_price * 0.98,
            'bb_upper': current_price * 1.02,
            'bb_middle': current_price,
            'ema_9_15m': current_price,
            'ema_21_15m': current_price,
            'ema_20_15m': current_price,
            'ema_50_daily': current_price,
            'weekly_support': current_price * 0.95,
            'macd_5m': 0.0,
            'macd_signal_5m': 0.0,
            'macd_histogram_5m': 0.0,
            'stoch_k': 50.0,
            'stoch_d': 50.0,
            'atr_5m': current_price * 0.01,
            'volatility_ratio': 1.0,
            'btc_strength': 0.0,
            'volume': 0.0,
            'volume_avg': 1.0,
        }
        
        # --- RSI Calculations ---
        try:
            indicator_values['rsi_5m'] = ta.momentum.RSIIndicator(data['5m']['close'], window=7).rsi().iloc[-1]
            indicator_values['rsi_15m'] = ta.momentum.RSIIndicator(data['15m']['close'], window=7).rsi().iloc[-1]
            indicator_values['rsi_1h'] = ta.momentum.RSIIndicator(data['1h']['close'], window=14).rsi().iloc[-1]
        except Exception as e:
            self.log_message(f"RSI calculation error: {str(e)[:30]}", "warning")
        
        # --- Bollinger Bands ---
        try:
            bb_5m = ta.volatility.BollingerBands(data['5m']['close'], window=20, window_dev=2)
            indicator_values['bb_lower'] = bb_5m.bollinger_lband().iloc[-1]
            indicator_values['bb_upper'] = bb_5m.bollinger_hband().iloc[-1]
            indicator_values['bb_middle'] = bb_5m.bollinger_mavg().iloc[-1]
        except Exception as e:
            self.log_message(f"BB calculation error: {str(e)[:30]}", "warning")
        
        # --- EMAs ---
        try:
            indicator_values['ema_9_15m'] = ta.trend.EMAIndicator(data['15m']['close'], window=9).ema_indicator().iloc[-1]
            indicator_values['ema_21_15m'] = ta.trend.EMAIndicator(data['15m']['close'], window=21).ema_indicator().iloc[-1]
            indicator_values['ema_20_15m'] = ta.trend.EMAIndicator(data['15m']['close'], window=20).ema_indicator().iloc[-1]
            indicator_values['ema_50_daily'] = ta.trend.EMAIndicator(data['1d']['close'], window=50).ema_indicator().iloc[-1]
        except Exception as e:
            self.log_message(f"EMA calculation error: {str(e)[:30]}", "warning")
        
        # --- MACD ---
        try:
            macd_indicator = ta.trend.MACD(data['5m']['close'], window_slow=26, window_fast=12, window_sign=9)
            indicator_values['macd_5m'] = macd_indicator.macd().iloc[-1]
            indicator_values['macd_signal_5m'] = macd_indicator.macd_signal().iloc[-1]
            indicator_values['macd_histogram_5m'] = macd_indicator.macd_diff().iloc[-1]
        except Exception as e:
            self.log_message(f"MACD calculation error: {str(e)[:30]}", "warning")
        
        # --- Stochastic ---
        try:
            stoch_indicator = ta.momentum.StochasticOscillator(data['5m']['high'], data['5m']['low'], data['5m']['close'], window=14, smooth_window=3)
            indicator_values['stoch_k'] = stoch_indicator.stoch().iloc[-1]
            indicator_values['stoch_d'] = stoch_indicator.stoch_signal().iloc[-1]
        except Exception as e:
            self.log_message(f"Stochastic calculation error: {str(e)[:30]}", "warning")
        
        # --- ATR ---
        try:
            atr_indicator = ta.volatility.AverageTrueRange(data['5m']['high'], data['5m']['low'], data['5m']['close'], window=14)
            indicator_values['atr_5m'] = atr_indicator.average_true_range().iloc[-1]
        except Exception as e:
            self.log_message(f"ATR calculation error: {str(e)[:30]}", "warning")
        
        # --- Volume Analysis ---
        try:
            indicator_values['volume'] = float(data['5m']['volume'].iloc[-1])
            indicator_values['volume_avg'] = data['5m']['volume'].rolling(20).mean().iloc[-1]
            # Make sure volume_avg is not zero to avoid division by zero
            if pd.isna(indicator_values['volume_avg']) or indicator_values['volume_avg'] <= 0:
                indicator_values['volume_avg'] = indicator_values['volume'] if indicator_values['volume'] > 0 else 1.0
        except Exception as e:
            self.log_message(f"Volume calculation error: {str(e)[:30]}", "warning")
        
        # --- Weekly Support ---
        try:
            indicator_values['weekly_support'] = data['1d']['low'].tail(7).min()
        except Exception as e:
            self.log_message(f"Support calculation error: {str(e)[:30]}", "warning")
        
        # --- BTC Trend Strength ---
        try:
            price_vs_ema50 = (current_price - indicator_values['ema_50_daily']) / indicator_values['ema_50_daily'] * 100
            indicator_values['btc_trend'] = "UP" if price_vs_ema50 > -2 else "DOWN"
            indicator_values['btc_strength'] = abs(price_vs_ema50)
        except Exception as e:
            indicator_values['btc_trend'] = "UP"  # Default to UP
            self.log_message(f"Trend calculation error: {str(e)[:30]}", "warning")
        
        # --- Volatility Ratio ---
        try:
            bb_width = (indicator_values['bb_upper'] - indicator_values['bb_lower']) / indicator_values['bb_middle']
            
            # Calculate historical BB width
            historical_bb_width = []
            for i in range(1, 20):
                try:
                    if i < len(data['5m']):
                        window_data = data['5m']['close'].iloc[-20-i:-i]
                        if len(window_data) >= 20:
                            hist_bb = ta.volatility.BollingerBands(window_data, window=20, window_dev=2)
                            upper = hist_bb.bollinger_hband().iloc[-1]
                            lower = hist_bb.bollinger_lband().iloc[-1]
                            middle = hist_bb.bollinger_mavg().iloc[-1]
                            if middle > 0 and not pd.isna(middle):
                                hist_width = (upper - lower) / middle
                                historical_bb_width.append(hist_width)
                except:
                    continue
            
            avg_bb_width = np.mean(historical_bb_width) if historical_bb_width else bb_width
            indicator_values['volatility_ratio'] = bb_width / avg_bb_width if avg_bb_width > 0 else 1.0
        except Exception as e:
            self.log_message(f"Volatility ratio calculation error: {str(e)[:30]}", "warning")
        
        # Check for any NaN values and replace with defaults
        for key, value in indicator_values.items():
            if pd.isna(value) or np.isinf(value):
                if key == 'rsi_5m' or key == 'rsi_15m' or key == 'rsi_1h':
                    indicator_values[key] = 50.0
                elif key == 'stoch_k' or key == 'stoch_d':
                    indicator_values[key] = 50.0
                elif key == 'volume' or key == 'volume_avg':
                    indicator_values[key] = 1.0
                elif key in ['macd_5m', 'macd_signal_5m', 'macd_histogram_5m']:
                    indicator_values[key] = 0.0
                elif key == 'volatility_ratio':
                    indicator_values[key] = 1.0
                else:
                    indicator_values[key] = current_price * 0.98 if 'lower' in key else current_price * 1.02
        
        # Create and return MarketData object with all calculated indicators
        return MarketData(
            price=current_price,
            rsi_5m=float(indicator_values['rsi_5m']),
            rsi_15m=float(indicator_values['rsi_15m']),
            rsi_1h=float(indicator_values['rsi_1h']),
            volume=float(indicator_values['volume']),
            volume_avg=float(indicator_values['volume_avg']),
            bb_lower=float(indicator_values['bb_lower']),
            bb_upper=float(indicator_values['bb_upper']),
            bb_middle=float(indicator_values['bb_middle']),
            ema_9_15m=float(indicator_values['ema_9_15m']),
            ema_21_15m=float(indicator_values['ema_21_15m']),
            ema_20_15m=float(indicator_values['ema_20_15m']),
            ema_50_daily=float(indicator_values['ema_50_daily']),
            weekly_support=float(indicator_values['weekly_support']),
            btc_trend=str(indicator_values['btc_trend']),
            macd_5m=float(indicator_values['macd_5m']),
            macd_signal_5m=float(indicator_values['macd_signal_5m']),
            macd_histogram_5m=float(indicator_values['macd_histogram_5m']),
            stoch_k=float(indicator_values['stoch_k']),
            stoch_d=float(indicator_values['stoch_d']),
            atr_5m=float(indicator_values['atr_5m']),
            volatility_ratio=float(indicator_values['volatility_ratio']),
            btc_strength=float(indicator_values['btc_strength']),
            timestamp=datetime.now()
        )
    except Exception as e:
        self.log_message(f"Fatal indicator calculation error: {str(e)}", "error")
        return None

def run_scanner(self):
    """Main scanning loop with improved handling of failed calculations"""
    while self.running:
        try:
            self.log_message("Fetching top 35 gainers...", "info")
            self.top_gainers = self.get_top_gainers()
            
            if not self.top_gainers:
                self.log_message("No gainers found, retrying in 30s", "warning")
                time.sleep(30)
                continue
                
            self.scanning_symbols = [coin['symbol'] for coin in self.top_gainers[:35]]
            
            if not self.scanning_symbols:
                self.log_message("No symbols to scan", "warning")
                time.sleep(30)
                continue
            
            active_positions = self.position_manager.get_active_symbols()
            available_symbols = [s for s in self.scanning_symbols if s not in active_positions]
            
            signals_found = 0
            scanned_count = 0
            failed_count = 0
            
            # Don't clear all data, just mark as stale
            for symbol in list(self.current_data.keys()):
                if symbol not in self.scanning_symbols:
                    del self.current_data[symbol]  # Remove old symbols
            
            self.log_message(f"Starting scan of {len(available_symbols)} coins", "info")
            
            for i, symbol in enumerate(available_symbols):
                try:
                    self.current_scanning_symbol = symbol.replace('USDT', '')
                    
                    # Update progress in stats
                    self.scan_stats['total_scanned'] = scanned_count
                    
                    # Get market data with retries
                    market_data = self.get_binance_data(symbol)
                    if not market_data or '5m' not in market_data:
                        failed_count += 1
                        self.current_data[symbol] = None
                        continue
                    
                    # Calculate indicators with improved error handling
                    current_data = self.calculate_indicators(market_data)
                    if current_data is None:
                        failed_count += 1
                        self.current_data[symbol] = None
                        continue
                    
                    # Store calculated data
                    self.current_data[symbol] = current_data
                    scanned_count += 1
                    
                    # Calculate strategy conditions
                    conditions = self.check_strategy_conditions(current_data)
                    
                    # Log progress every 10 coins
                    if i > 0 and i % 10 == 0:
                        self.log_message(f"Scanned {scanned_count} coins, {failed_count} failed", "info")
                    
                    # Check for entry signals
                    signal = self.check_entry_signals(symbol, current_data, conditions)
                    
                    if signal:
                        signals_found += 1
                        coin_name = symbol.replace('USDT', '')
                        self.log_message(f"SIGNAL: {coin_name} LONG ENTRY - Level {signal['entry_level']}", "success")
                        
                        with open('signals.json', 'a') as f:
                            f.write(json.dumps(signal) + '\n')
                    
                    # Add a small delay to avoid rate limiting
                    time.sleep(0.2)
                    
                except Exception as e:
                    self.log_message(f"Error scanning {symbol}: {str(e)[:30]}", "error")
                    failed_count += 1
                    self.current_data[symbol] = None
                    continue
            
            # Complete scan cycle
            self.current_scanning_symbol = None
            self.scan_stats['scan_cycles'] += 1
            self.scan_stats['total_scanned'] = scanned_count
            self.scan_stats['signals_found'] += signals_found
            self.scan_stats['last_scan_time'] = datetime.now()
            
            if signals_found > 0:
                self.log_message(f"Scan complete: {signals_found} signals from {scanned_count} coins ({failed_count} failed)", "success")
            else:
                self.log_message(f"Scan complete: {scanned_count} coins analyzed, {failed_count} failed, no signals", "info")
            
            # Wait before next scan cycle
            time.sleep(config.SCAN_INTERVAL)
            
        except Exception as e:
            self.log_message(f"Scanner error: {str(e)}", "error")
            time.sleep(30)

def get_order_book_imbalance(self, symbol: str) -> Optional[float]:
    """Get order book imbalance ratio with better error handling and fallback"""
    try:
        url = "https://api.binance.com/api/v3/depth"
        params = {'symbol': symbol, 'limit': 100}
        
        # Use retries
        for attempt in range(3):
            try:
                response = requests.get(url, params=params, timeout=5)
                
                if response.status_code == 200:
                    depth_data = response.json()
                    
                    if 'bids' not in depth_data or 'asks' not in depth_data:
                        time.sleep(1)
                        continue
                    
                    if not depth_data['bids'] or not depth_data['asks']:
                        return 1.0  # Default to neutral if no data
                    
                    total_bid_volume = sum(float(bid[1]) for bid in depth_data['bids'])
                    total_ask_volume = sum(float(ask[1]) for ask in depth_data['asks'])
                    
                    if total_ask_volume > 0:
                        ratio = total_bid_volume / total_ask_volume
                        # Cap the ratio to avoid extreme values
                        return min(5.0, max(0.2, ratio))
                    else:
                        return 2.0  # Default high imbalance if no asks
                        
                time.sleep(0.5)
            except requests.exceptions.RequestException:
                time.sleep(1)
        
        return 1.0  # Default to neutral if all attempts failed
    except Exception as e:
        self.log_message(f"Order book error for {symbol}: {str(e)[:20]}", "error")
        return 1.0  # Default to neutral

def calculate_atr_levels(self, data: Dict[str, pd.DataFrame], entry_price: float) -> Dict[str, float]:
    """Calculate ATR-based levels with improved error handling and fallback"""
    try:
        # Ensure we have valid data
        if '5m' not in data or data['5m'].empty:
            return self._get_default_levels(entry_price)
            
        df_5m = data['5m'].copy()
        
        # Convert to numeric to avoid calculation errors
        df_5m['high'] = pd.to_numeric(df_5m['high'], errors='coerce')
        df_5m['low'] = pd.to_numeric(df_5m['low'], errors='coerce')
        df_5m['close'] = pd.to_numeric(df_5m['close'], errors='coerce')
        
        # Check if there are NaN values
        if df_5m['high'].isna().any() or df_5m['low'].isna().any() or df_5m['close'].isna().any():
            return self._get_default_levels(entry_price)
        
        # Calculate True Range components
        df_5m['high_low'] = df_5m['high'] - df_5m['low']
        df_5m['high_close_prev'] = abs(df_5m['high'] - df_5m['close'].shift(1))
        df_5m['low_close_prev'] = abs(df_5m['low'] - df_5m['close'].shift(1))
        df_5m['true_range'] = df_5m[['high_low', 'high_close_prev', 'low_close_prev']].max(axis=1)
        
        # Calculate ATR (14-period average)
        atr_14 = df_5m['true_range'].rolling(window=14).mean().iloc[-1]
        
        # Validate ATR
        if pd.isna(atr_14) or atr_14 <= 0:
            atr_14 = entry_price * 0.02  # 2% default
        
        # Calculate levels and ensure they're valid
        stop_loss = float(entry_price - (0.8 * atr_14))
        tp1 = float(entry_price + (1.0 * atr_14))
        tp2 = float(entry_price + (1.8 * atr_14))
        
        # Validate levels (ensure they make sense)
        if stop_loss <= 0 or stop_loss >= entry_price:
            stop_loss = entry_price * 0.99
            
        if tp1 <= entry_price:
            tp1 = entry_price * 1.008
            
        if tp2 <= tp1:
            tp2 = tp1 * 1.005
        
        return {
            'atr': float(atr_14),
            'stop_loss': stop_loss,
            'tp1': tp1,
            'tp2': tp2
        }
    except Exception as e:
        self.log_message(f"ATR calculation error: {str(e)[:20]}", "error")
        return self._get_default_levels(entry_price)

def _get_default_levels(self, entry_price: float) -> Dict[str, float]:
    """Get default levels based on percentage of price"""
    return {
        'atr': float(entry_price * 0.02),
        'stop_loss': float(entry_price * 0.99),
        'tp1': float(entry_price * 1.008),
        'tp2': float(entry_price * 1.015)
    }

def check_strategy_conditions(self, data: MarketData) -> Dict[str, bool]:
    """Check strategy conditions with better error handling"""
    conditions = {}
    
    try:
        # Adaptive thresholds based on volatility
        high_vol = data.volatility_ratio > 1.2
        bb_threshold = 1.015 if high_vol else 1.008
        rsi_threshold = 55 if high_vol else 50
        
        # CORE CONDITION 1: Bollinger Band Touch (ADAPTIVE)
        bb_touch_threshold = data.bb_lower * bb_threshold
        conditions['bb_touch'] = data.price <= bb_touch_threshold
        
        # CORE CONDITION 2: RSI Oversold but not extreme (ADAPTIVE)
        conditions['rsi_oversold'] = data.rsi_5m < rsi_threshold and data.rsi_5m > 25
        
        # CORE CONDITION 3: MACD Momentum Building (NEW)
        conditions['macd_momentum'] = (data.macd_histogram_5m > -0.001) or (data.macd_5m > data.macd_signal_5m)
        
        # CORE CONDITION 4: Stochastic Oversold Recovery (NEW)
        conditions['stoch_recovery'] = (data.stoch_k < 30 and data.stoch_k > data.stoch_d) or (data.stoch_k < 40 and data.stoch_k > 25)
        
        # CORE CONDITION 5: Trend Alignment (SIMPLIFIED)
        trend_ok = (data.price > data.ema_20_15m * 0.998) or (data.btc_strength > 3 and data.btc_trend == "UP")
        conditions['trend_alignment'] = trend_ok
        
        # BONUS CONDITION 6: Volume Confirmation (OPTIONAL - not required)
        volume_ratio = data.volume / data.volume_avg if data.volume_avg > 0 else 0
        conditions['volume_confirm'] = (volume_ratio < 0.8) or (volume_ratio > 1.3)
        
    except Exception as e:
        # If any condition check fails, set all to False
        self.log_message(f"Error checking conditions: {str(e)[:30]}", "error")
        conditions = {
            'bb_touch': False,
            'rsi_oversold': False,
            'macd_momentum': False,
            'stoch_recovery': False,
            'trend_alignment': False,
            'volume_confirm': False
        }
    
    return conditions