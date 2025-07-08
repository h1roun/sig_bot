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
        """Setup the terminal layout optimized for 14" MacBook - improved proportions"""
        self.layout.split_column(
            Layout(name="header", size=2),
            Layout(name="body"),
            Layout(name="footer", size=2)
        )
        
        # IMPROVED: Better proportions - reduce gainers width, increase conditions detail
        self.layout["body"].split_row(
            Layout(name="left", ratio=1),      # Stats + Positions
            Layout(name="middle", ratio=1),    # Signals + Logs  
            Layout(name="right", ratio=1.3),   # Gainers table (reduced from 2)
            Layout(name="details", ratio=1.7)  # Top conditions (increased from 1)
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
        
        # Details column: Top conditions with more space
        self.layout["details"].split_column(
            Layout(name="conditions_detail")
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
        """Compact gainers panel for reduced width"""
        table = Table(title="Top 35 Gainers", box=box.SIMPLE)
        table.add_column("Coin", style="cyan", width=4)
        table.add_column("Price", style="white", width=6)  # Reduced from 7
        table.add_column("Chg%", style="white", width=4)   # Reduced from 5
        table.add_column("Core", style="white", width=3)   # Reduced from 4
        table.add_column("Vol", style="white", width=4)    # Reduced from 5
        table.add_column("RSI", style="white", width=3)    # Reduced from 4
        table.add_column("Status", style="white", width=5) # Reduced from 6
        
        display_gainers = self.top_gainers[:35]
        
        for gainer in display_gainers:
            symbol = gainer['symbol']
            data = self.current_data.get(symbol)
            
            if data and hasattr(data, 'volume') and hasattr(data, 'volume_avg') and hasattr(data, 'rsi_5m'):
                # Only calculate if we have valid data
                try:
                    conditions = self.check_strategy_conditions(data)
                    core_conditions = ['bb_touch', 'rsi_oversold', 'macd_momentum', 'stoch_recovery', 'trend_alignment']
                    core_conditions_met = sum(conditions[cond] for cond in core_conditions)
                    
                    # Safe volume calculation
                    if data.volume_avg > 0 and not pd.isna(data.volume) and not pd.isna(data.volume_avg):
                        volume_str = f"{data.volume/data.volume_avg:.1f}x"
                    else:
                        volume_str = "N/A"
                    
                    # Safe RSI calculation
                    if not pd.isna(data.rsi_5m) and data.rsi_5m > 0:
                        rsi_str = f"{data.rsi_5m:.0f}"
                    else:
                        rsi_str = "N/A"
                        
                except Exception as e:
                    # Fallback if conditions calculation fails
                    core_conditions_met = 0
                    volume_str = "ERR"
                    rsi_str = "ERR"
            else:
                # No data available yet
                core_conditions_met = 0
                volume_str = "..." if symbol == f"{self.current_scanning_symbol}USDT" else "N/A"
                rsi_str = "..." if symbol == f"{self.current_scanning_symbol}USDT" else "N/A"
            
            change_style = "green" if gainer['change_24h'] > 0 else "red"
            conditions_style = "green" if core_conditions_met >= 4 else "yellow" if core_conditions_met >= 3 else "white"
            
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
            
            table.add_row(
                gainer['coin'][:4],
                f"${gainer['price']:.2f}",  # Reduced decimal places
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
        """Enhanced conditions panel with better spacing and readability"""
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
                title="Top Conditions Analysis",
                style="white"
            )
        
        # Create layout with proper spacing
        main_layout = Layout()
        main_layout.split_column(
            *[Layout(name=f"coin_{i}") for i in range(3)]
        )
        
        for i, coin_info in enumerate(top_3_coins):
            conditions = coin_info['conditions']
            data = coin_info['data']
            
            # Create enhanced table for this coin with better spacing
            coin_table = Table(
                title=f"{coin_info['coin']} - {coin_info['core_conditions_met']}/5 Core ({coin_info['total_conditions']}/6 Total)", 
                box=box.ROUNDED,  # Better looking box style
                title_style="bold green" if coin_info['core_conditions_met'] >= 4 else "bold yellow" if coin_info['core_conditions_met'] >= 3 else "cyan",
                show_header=True,
                header_style="bold blue"
            )
            
            coin_table.add_column("Condition", style="white", width=12, no_wrap=True)
            coin_table.add_column("Status", style="white", width=4, justify="center")
            coin_table.add_column("Value", style="white", width=10, justify="right")
            coin_table.add_column("Target", style="white", width=12, justify="center")
            
            # Price and change info with better formatting
            coin_table.add_row(
                "💰 Price",
                "",
                f"${coin_info['price']:.4f}",
                Text(f"{coin_info['change']:+.1f}%", style="green" if coin_info['change'] > 0 else "red")
            )
            
            # Add separator
            coin_table.add_row("─" * 12, "─" * 4, "─" * 10, "─" * 12)
            
            # 1. BB Touch (CORE) - Enhanced display
            bb_distance = ((data.price - data.bb_lower) / data.bb_lower) * 100
            bb_style = "green" if conditions['bb_touch'] else "red"
            coin_table.add_row(
                "📊 BB Touch *",
                Text("✅" if conditions['bb_touch'] else "❌", style=bb_style),
                f"{bb_distance:.2f}%",
                "< 1.5%"
            )
            
            # 2. RSI Oversold (CORE)
            rsi_style = "green" if conditions['rsi_oversold'] else "red"
            coin_table.add_row(
                "📈 RSI Oversold *",
                Text("✅" if conditions['rsi_oversold'] else "❌", style=rsi_style),
                f"{data.rsi_5m:.1f}",
                "25-55"
            )
            
            # 3. MACD Momentum (CORE)
            macd_style = "green" if conditions['macd_momentum'] else "red"
            coin_table.add_row(
                "⚡ MACD Momentum *",
                Text("✅" if conditions['macd_momentum'] else "❌", style=macd_style),
                f"{data.macd_histogram_5m:.4f}",
                "> -0.001"
            )
            
            # 4. Stoch Recovery (CORE)
            stoch_style = "green" if conditions['stoch_recovery'] else "red"
            coin_table.add_row(
                "🔄 Stoch Recovery *",
                Text("✅" if conditions['stoch_recovery'] else "❌", style=stoch_style),
                f"{data.stoch_k:.1f}",
                "< 40"
            )
            
            # 5. Trend Alignment (CORE)
            trend_style = "green" if conditions['trend_alignment'] else "red"
            coin_table.add_row(
                "📊 Trend Align *",
                Text("✅" if conditions['trend_alignment'] else "❌", style=trend_style),
                data.btc_trend,
                "Aligned"
            )
            
            # Add separator
            coin_table.add_row("─" * 12, "─" * 4, "─" * 10, "─" * 12)
            
            # 6. Volume Confirm (BONUS)
            volume_style = "green" if conditions['volume_confirm'] else "dim"
            volume_ratio = data.volume / data.volume_avg
            coin_table.add_row(
                "📊 Volume (Bonus)",
                Text("✅" if conditions['volume_confirm'] else "○", style=volume_style),
                f"{volume_ratio:.2f}x",
                "<0.8 or >1.3"
            )
            
            # Assign to layout
            main_layout[f"coin_{i}"].update(Panel(coin_table, expand=True))
        
        # Fill remaining slots with empty panels
        for i in range(len(top_3_coins), 3):
            main_layout[f"coin_{i}"].update(Panel("", expand=True))
        
        return Panel(
            main_layout, 
            title="📊 5-Core Strategy Analysis (⭐ = Required, Need 4/5 Core)", 
            title_align="center",
            style="green" if top_3_coins and top_3_coins[0]['core_conditions_met'] >= 4 else "white",
            border_style="bold"
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
        """Fetch real-time data from Binance API"""
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
                continue
                
        return data
    
    def calculate_indicators(self, data: Dict[str, pd.DataFrame]) -> Optional[MarketData]:
        """Calculate all technical indicators with better error handling"""
        try:
            # Validate input data first
            required_intervals = ['5m', '15m', '1h', '1d']
            for interval in required_intervals:
                if interval not in data or data[interval].empty:
                    return None
            
            current_price = float(data['5m']['close'].iloc[-1])
            
            # Validate price
            if pd.isna(current_price) or current_price <= 0:
                return None
            
            # RSI indicators with validation
            try:
                rsi_5m = ta.momentum.RSIIndicator(data['5m']['close'], window=7).rsi().iloc[-1]
                if pd.isna(rsi_5m):
                    rsi_5m = 50.0  # Default neutral value
            except:
                rsi_5m = 50.0
            
            try:
                rsi_15m = ta.momentum.RSIIndicator(data['15m']['close'], window=7).rsi().iloc[-1]
                if pd.isna(rsi_15m):
                    rsi_15m = 50.0
            except:
                rsi_15m = 50.0
            
            try:
                rsi_1h = ta.momentum.RSIIndicator(data['1h']['close'], window=14).rsi().iloc[-1]
                if pd.isna(rsi_1h):
                    rsi_1h = 50.0
            except:
                rsi_1h = 50.0
        
            # Enhanced Bollinger Bands with validation
            try:
                bb_5m = ta.volatility.BollingerBands(data['5m']['close'], window=20, window_dev=2)
                bb_lower = bb_5m.bollinger_lband().iloc[-1]
                bb_upper = bb_5m.bollinger_hband().iloc[-1]
                bb_middle = bb_5m.bollinger_mavg().iloc[-1]
                
                # Validate BB values
                if pd.isna(bb_lower) or pd.isna(bb_upper) or pd.isna(bb_middle):
                    bb_lower = current_price * 0.98
                    bb_upper = current_price * 1.02
                    bb_middle = current_price
            except:
                bb_lower = current_price * 0.98
                bb_upper = current_price * 1.02
                bb_middle = current_price
        
            # EMA indicators with validation
            try:
                ema_9_15m = ta.trend.EMAIndicator(data['15m']['close'], window=9).ema_indicator().iloc[-1]
                ema_21_15m = ta.trend.EMAIndicator(data['15m']['close'], window=21).ema_indicator().iloc[-1]
                ema_20_15m = ta.trend.EMAIndicator(data['15m']['close'], window=20).ema_indicator().iloc[-1]
                ema_50_daily = ta.trend.EMAIndicator(data['1d']['close'], window=50).ema_indicator().iloc[-1]
                
                # Validate EMA values
                if pd.isna(ema_9_15m): ema_9_15m = current_price
                if pd.isna(ema_21_15m): ema_21_15m = current_price
                if pd.isna(ema_20_15m): ema_20_15m = current_price
                if pd.isna(ema_50_daily): ema_50_daily = current_price
            except:
                ema_9_15m = current_price
                ema_21_15m = current_price
                ema_20_15m = current_price
                ema_50_daily = current_price
        
            # MACD for momentum confirmation with validation
            try:
                macd_indicator = ta.trend.MACD(data['5m']['close'], window_slow=26, window_fast=12, window_sign=9)
                macd_5m = macd_indicator.macd().iloc[-1]
                macd_signal_5m = macd_indicator.macd_signal().iloc[-1]
                macd_histogram_5m = macd_indicator.macd_diff().iloc[-1]
                
                # Validate MACD values
                if pd.isna(macd_5m): macd_5m = 0.0
                if pd.isna(macd_signal_5m): macd_signal_5m = 0.0
                if pd.isna(macd_histogram_5m): macd_histogram_5m = 0.0
            except:
                macd_5m = 0.0
                macd_signal_5m = 0.0
                macd_histogram_5m = 0.0
        
            # Stochastic for oversold confirmation with validation
            try:
                stoch_indicator = ta.momentum.StochasticOscillator(data['5m']['high'], data['5m']['low'], data['5m']['close'], window=14, smooth_window=3)
                stoch_k = stoch_indicator.stoch().iloc[-1]
                stoch_d = stoch_indicator.stoch_signal().iloc[-1]
                
                # Validate Stochastic values
                if pd.isna(stoch_k): stoch_k = 50.0
                if pd.isna(stoch_d): stoch_d = 50.0
            except:
                stoch_k = 50.0
                stoch_d = 50.0
        
            # ATR for volatility with validation
            try:
                atr_indicator = ta.volatility.AverageTrueRange(data['5m']['high'], data['5m']['low'], data['5m']['close'], window=14)
                atr_5m = atr_indicator.average_true_range().iloc[-1]
                if pd.isna(atr_5m): atr_5m = current_price * 0.02  # 2% default
            except:
                atr_5m = current_price * 0.02
        
            # Volume analysis with validation
            try:
                current_volume = float(data['5m']['volume'].iloc[-1])
                volume_avg = data['5m']['volume'].rolling(20).mean().iloc[-1]
                
                # Validate volume values
                if pd.isna(current_volume) or current_volume <= 0:
                    current_volume = 1000.0  # Default volume
                if pd.isna(volume_avg) or volume_avg <= 0:
                    volume_avg = current_volume  # Use current as average
            except:
                current_volume = 1000.0
                volume_avg = 1000.0
        
            # Support level with validation
            try:
                weekly_support = data['1d']['low'].tail(7).min()
                if pd.isna(weekly_support):
                    weekly_support = current_price * 0.95  # 5% below current price
            except:
                weekly_support = current_price * 0.95
        
            # Enhanced BTC trend strength with validation
            try:
                price_vs_ema50 = (current_price - ema_50_daily) / ema_50_daily * 100
                btc_trend = "UP" if price_vs_ema50 > -2 else "DOWN"
                btc_strength = abs(price_vs_ema50)
                
                # Validate trend values
                if pd.isna(price_vs_ema50):
                    price_vs_ema50 = 0.0
                    btc_strength = 0.0
                    btc_trend = "NEUTRAL"
            except:
                price_vs_ema50 = 0.0
                btc_strength = 0.0
                btc_trend = "NEUTRAL"
        
            # Volatility ratio for market regime with validation
            try:
                bb_width = (bb_upper - bb_lower) / bb_middle
                historical_bb_width = []
                
                for i in range(min(20, len(data['5m']) - 20)):
                    try:
                        subset = data['5m']['close'].iloc[-(20-i):]
                        if len(subset) >= 20:
                            hist_bb = ta.volatility.BollingerBands(subset, window=20, window_dev=2)
                            hist_width = (hist_bb.bollinger_hband().iloc[-1] - hist_bb.bollinger_lband().iloc[-1]) / hist_bb.bollinger_mavg().iloc[-1]
                            if not pd.isna(hist_width) and hist_width > 0:
                                historical_bb_width.append(hist_width)
                    except:
                        continue
            
                avg_bb_width = np.mean(historical_bb_width) if historical_bb_width else bb_width
                volatility_ratio = bb_width / avg_bb_width if avg_bb_width > 0 else 1.0
                
                # Validate volatility ratio
                if pd.isna(volatility_ratio) or volatility_ratio <= 0:
                    volatility_ratio = 1.0
            except:
                volatility_ratio = 1.0
        
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
            # Return None if we can't calculate indicators properly
            return None

    def check_strategy_conditions(self, data: MarketData) -> Dict[str, bool]:
        """OPTIMIZED: Check only 5 CORE conditions with adaptive thresholds"""
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
        
        # CORE CONDITION 3: MACD Momentum Building (NEW)
        # MACD histogram increasing (momentum building) OR MACD above signal
        conditions['macd_momentum'] = (data.macd_histogram_5m > -0.001) or (data.macd_5m > data.macd_signal_5m)
        
        # CORE CONDITION 4: Stochastic Oversold Recovery (NEW)
        # Stochastic oversold but showing signs of recovery
        conditions['stoch_recovery'] = (data.stoch_k < 30 and data.stoch_k > data.stoch_d) or (data.stoch_k < 40 and data.stoch_k > 25)
        
        # CORE CONDITION 5: Trend Alignment (SIMPLIFIED)
        # Price above EMA20 (15m) AND general uptrend OR strong bounce potential
        trend_ok = (data.price > data.ema_20_15m * 0.998) or (data.btc_strength > 3 and data.btc_trend == "UP")
        conditions['trend_alignment'] = trend_ok
        
        # BONUS CONDITION 6: Volume Confirmation (OPTIONAL - not required)
        # Either declining volume (accumulation) OR increasing volume (breakout)
        volume_ratio = data.volume / data.volume_avg
        conditions['volume_confirm'] = (volume_ratio < 0.8) or (volume_ratio > 1.3)
        
        return conditions

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
        """Main scanning loop with better error handling"""
        while self.running:
            try:
                self.log_message("Fetching top 35 gainers...", "info")
                self.top_gainers = self.get_top_gainers()
                self.scanning_symbols = [coin['symbol'] for coin in self.top_gainers[:35]]
                
                if not self.scanning_symbols:
                    self.log_message("No symbols to scan", "warning")
                    time.sleep(30)
                    continue
                
                active_positions = self.position_manager.get_active_symbols()
                available_symbols = [s for s in self.scanning_symbols if s not in active_positions]
                
                signals_found = 0
                scanned_count = 0
                
                # Clear stale data for symbols not in current top gainers
                current_symbols = set(self.scanning_symbols)
                stale_symbols = [s for s in self.current_data.keys() if s not in current_symbols]
                for symbol in stale_symbols:
                    del self.current_data[symbol]
                
                self.log_message(f"Starting scan of {len(available_symbols)} coins", "info")
                
                for i, symbol in enumerate(available_symbols):
                    try:
                        self.current_scanning_symbol = symbol.replace('USDT', '')
                        
                        # Update progress in stats
                        self.scan_stats['total_scanned'] = scanned_count
                        
                        market_data = self.get_binance_data(symbol)
                        if not market_data or '5m' not in market_data or market_data['5m'].empty:
                            self.current_data[symbol] = None
                            self.log_message(f"No data for {symbol.replace('USDT', '')}", "warning")
                            continue
                            
                        current_data = self.calculate_indicators(market_data)
                        if not current_data:
                            self.current_data[symbol] = None
                            self.log_message(f"Failed indicators for {symbol.replace('USDT', '')}", "warning")
                            continue
                        
                        self.current_data[symbol] = current_data
                        scanned_count += 1
                        
                        conditions = self.check_strategy_conditions(current_data)
                        core_conditions = ['bb_touch', 'rsi_oversold', 'macd_momentum', 'stoch_recovery', 'trend_alignment']
                        core_conditions_met = sum(conditions[cond] for cond in core_conditions)
                        
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
                        coin_name = symbol.replace('USDT', '') if symbol else "Unknown"
                        self.log_message(f"Error scanning {coin_name}: {str(e)[:15]}", "error")
                        self.current_data[symbol] = None
                        continue
                
                # Complete scan cycle
                self.current_scanning_symbol = None
                self.scan_stats['scan_cycles'] += 1
                self.scan_stats['total_scanned'] = scanned_count
                self.scan_stats['signals_found'] += signals_found
                self.scan_stats['last_scan_time'] = datetime.now()
                
                if signals_found > 0:
                    self.log_message(f"Scan complete: {signals_found} signals from {scanned_count} coins", "success")
                else:
                    self.log_message(f"Scan complete: {scanned_count} coins analyzed, no signals", "info")
                
                time.sleep(12)
                
            except Exception as e:
                self.log_message(f"Scanner error: {str(e)[:30]}", "error")
                time.sleep(30)

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