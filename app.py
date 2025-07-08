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
    ema_9_15m: float
    ema_21_15m: float
    ema_20_15m: float
    ema_50_daily: float
    weekly_support: float
    btc_trend: str
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
            Layout(name="details", ratio=1)    # Detailed conditions
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
        
        # Right column: Just gainers (fix the assignment)
        self.layout["right"].split_column(
            Layout(name="gainers")
        )
        
        # Details column: Condition breakdown
        self.layout["details"].split_column(
            Layout(name="current_scan", size=8),
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
        """Create top gainers panel with more compact view"""
        table = Table(title="Top 35 Gainers", box=box.SIMPLE)
        table.add_column("Coin", style="cyan", width=5)
        table.add_column("Price", style="white", width=8)
        table.add_column("Chg%", style="white", width=5)
        table.add_column("C", style="white", width=2)
        table.add_column("Status", style="white", width=8)
        
        # Show top 20 gainers in compact format
        display_gainers = self.top_gainers[:20]
        
        for gainer in display_gainers:
            symbol = gainer['symbol']
            data = self.current_data.get(symbol)
            
            if data:
                conditions = self.check_strategy_conditions(data)
                conditions_met = sum(conditions.values())
            else:
                conditions_met = 0
            
            change_style = "green" if gainer['change_24h'] > 0 else "red"
            conditions_style = "green" if conditions_met == 8 else "yellow" if conditions_met >= 6 else "white"
            
            if symbol == f"{self.current_scanning_symbol}USDT":
                status = "SCAN"
                status_style = "yellow"
            elif conditions_met == 8:
                status = "READY!"
                status_style = "red"
            elif conditions_met >= 6:
                status = "Near"
                status_style = "yellow"
            else:
                status = "Watch"
                status_style = "white"
            
            table.add_row(
                gainer['coin'][:5],
                f"${gainer['price']:.4f}",
                Text(f"{gainer['change_24h']:+.1f}", style=change_style),
                Text(f"{conditions_met}", style=conditions_style),
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
        """Create detailed conditions breakdown for current or top coins"""
        # Show conditions for currently scanning coin or top candidate
        target_symbol = None
        target_coin = None
        
        if self.current_scanning_symbol:
            target_symbol = f"{self.current_scanning_symbol}USDT"
            target_coin = self.current_scanning_symbol
        else:
            # Find coin with most conditions met
            best_coin = None
            best_conditions = 0
            for gainer in self.top_gainers[:10]:
                symbol = gainer['symbol']
                data = self.current_data.get(symbol)
                if data:
                    conditions = self.check_strategy_conditions(data)
                    conditions_met = sum(conditions.values())
                    if conditions_met > best_conditions:
                        best_conditions = conditions_met
                        best_coin = gainer
            
            if best_coin:
                target_symbol = best_coin['symbol']
                target_coin = best_coin['coin']
        
        if not target_symbol or target_symbol not in self.current_data:
            return Panel(
                Align.center(Text("No data available", style="dim")),
                title="Conditions Detail",
                style="white"
            )
        
        data = self.current_data[target_symbol]
        conditions = self.check_strategy_conditions(data)
        
        # Create detailed conditions table
        table = Table(title=f"{target_coin} Conditions", box=box.SIMPLE)
        table.add_column("Condition", style="white", width=12)
        table.add_column("Status", style="white", width=6)
        table.add_column("Value", style="white", width=8)
        
        # 1. Bollinger Band Touch
        bb_distance = ((data.price - data.bb_lower) / data.bb_lower) * 100
        bb_style = "green" if conditions['bb_touch'] else "red"
        table.add_row(
            "BB Touch",
            Text("✓" if conditions['bb_touch'] else "✗", style=bb_style),
            f"{bb_distance:.2f}%"
        )
        
        # 2. RSI 5m < 50
        rsi_5m_style = "green" if conditions['rsi_5m'] else "red"
        table.add_row(
            "RSI 5m < 50",
            Text("✓" if conditions['rsi_5m'] else "✗", style=rsi_5m_style),
            f"{data.rsi_5m:.1f}"
        )
        
        # 3. RSI 15m > 35
        rsi_15m_style = "green" if conditions['rsi_15m'] else "red"
        table.add_row(
            "RSI 15m > 35",
            Text("✓" if conditions['rsi_15m'] else "✗", style=rsi_15m_style),
            f"{data.rsi_15m:.1f}"
        )
        
        # 4. RSI 1h > 50
        rsi_1h_style = "green" if conditions['rsi_1h'] else "red"
        table.add_row(
            "RSI 1h > 50",
            Text("✓" if conditions['rsi_1h'] else "✗", style=rsi_1h_style),
            f"{data.rsi_1h:.1f}"
        )
        
        # 5. Volume Decline
        volume_ratio = data.volume / data.volume_avg
        volume_style = "green" if conditions['volume_decline'] else "red"
        table.add_row(
            "Volume Low",
            Text("✓" if conditions['volume_decline'] else "✗", style=volume_style),
            f"{volume_ratio:.2f}x"
        )
        
        # 6. Weekly Support
        support_distance = ((data.price - data.weekly_support) / data.weekly_support) * 100
        support_style = "green" if conditions['weekly_support'] else "red"
        table.add_row(
            "Above Support",
            Text("✓" if conditions['weekly_support'] else "✗", style=support_style),
            f"{support_distance:.1f}%"
        )
        
        # 7. EMA Stack
        ema_style = "green" if conditions['ema_stack'] else "red"
        price_ema_distance = ((data.price - data.ema_20_15m) / data.ema_20_15m) * 100
        table.add_row(
            "EMA Stack",
            Text("✓" if conditions['ema_stack'] else "✗", style=ema_style),
            f"{price_ema_distance:.1f}%"
        )
        
        # 8. Daily Trend
        trend_style = "green" if conditions['daily_trend'] else "red"
        table.add_row(
            "Daily Trend",
            Text("✓" if conditions['daily_trend'] else "✗", style=trend_style),
            data.btc_trend
        )
        
        # Summary
        conditions_met = sum(conditions.values())
        summary_style = "green" if conditions_met == 8 else "yellow" if conditions_met >= 6 else "red"
        table.add_row(
            "TOTAL",
            Text(f"{conditions_met}/8", style=summary_style),
            "READY!" if conditions_met == 8 else "Near" if conditions_met >= 6 else "Wait"
        )
        
        return Panel(table, style="green" if conditions_met >= 6 else "white")

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
        """Create enhanced logs panel"""
        table = Table(title="System Status", box=box.SIMPLE, show_header=False)
        table.add_column("", style="cyan", width=5)
        table.add_column("", style="white")
        
        # Show scan progress and system status
        scan_progress = f"{self.scan_stats['total_scanned']}/35"
        table.add_row("Scan", scan_progress)
        table.add_row("Cycle", str(self.scan_stats['scan_cycles']))
        table.add_row("Found", str(self.scan_stats['signals_found']))
        
        # Show recent important logs
        for alert in self.alerts[:2]:
            style = "green" if alert['level'] == "success" else "red" if alert['level'] == "error" else "yellow"
            message = alert['message'][:15]
            table.add_row(alert['time'][:5], Text(message, style=style))
        
        return Panel(table, style="white")

    def render_dashboard(self):
        """Render the complete dashboard with detailed info"""
        self.layout["header"].update(self.create_header())
        self.layout["stats"].update(self.create_stats_panel())
        self.layout["positions"].update(self.create_positions_panel())
        self.layout["signals"].update(self.create_signals_panel())
        self.layout["gainers"].update(self.create_gainers_panel())
        self.layout["logs"].update(self.create_logs_panel())
        self.layout["current_scan"].update(self.create_current_scan_panel())
        self.layout["conditions_detail"].update(self.create_conditions_detail_panel())
        self.layout["footer"].update(self.create_footer())
        
        return self.layout

    def create_footer(self) -> Panel:
        """Create enhanced footer with more info"""
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
        
        footer_text.append(f"Cycle: {self.scan_stats['scan_cycles']} | ", style="green")
        footer_text.append(f"Scanned: {self.scan_stats['total_scanned']}/35 | ", style="cyan")
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
        """Calculate all technical indicators"""
        try:
            current_price = float(data['5m']['close'].iloc[-1])
            
            rsi_5m = ta.momentum.RSIIndicator(data['5m']['close'], window=7).rsi().iloc[-1]
            rsi_15m = ta.momentum.RSIIndicator(data['15m']['close'], window=7).rsi().iloc[-1]
            rsi_1h = ta.momentum.RSIIndicator(data['1h']['close'], window=14).rsi().iloc[-1]
            
            bb_5m = ta.volatility.BollingerBands(data['5m']['close'], window=20, window_dev=2)
            bb_lower = bb_5m.bollinger_lband().iloc[-1]
            bb_upper = bb_5m.bollinger_hband().iloc[-1]
            
            ema_9_15m = ta.trend.EMAIndicator(data['15m']['close'], window=9).ema_indicator().iloc[-1]
            ema_21_15m = ta.trend.EMAIndicator(data['15m']['close'], window=21).ema_indicator().iloc[-1]
            ema_20_15m = ta.trend.EMAIndicator(data['15m']['close'], window=20).ema_indicator().iloc[-1]
            ema_50_daily = ta.trend.EMAIndicator(data['1d']['close'], window=50).ema_indicator().iloc[-1]
            
            current_volume = float(data['5m']['volume'].iloc[-1])
            volume_avg = data['5m']['volume'].rolling(20).mean().iloc[-1]
            
            weekly_support = data['1d']['low'].tail(7).min()
            btc_trend = "UP" if current_price > ema_50_daily else "DOWN"
            
            return MarketData(
                price=current_price,
                rsi_5m=rsi_5m,
                rsi_15m=rsi_15m,
                rsi_1h=rsi_1h,
                volume=current_volume,
                volume_avg=volume_avg,
                bb_lower=bb_lower,
                bb_upper=bb_upper,
                ema_9_15m=ema_9_15m,
                ema_21_15m=ema_21_15m,
                ema_20_15m=ema_20_15m,
                ema_50_daily=ema_50_daily,
                weekly_support=weekly_support,
                btc_trend=btc_trend,
                timestamp=datetime.now()
            )
        except Exception:
            return None
    
    def check_strategy_conditions(self, data: MarketData) -> Dict[str, bool]:
        """Check all strategy conditions"""
        conditions = {}
        
        bb_touch_threshold = data.bb_lower * 1.005
        conditions['bb_touch'] = data.price <= bb_touch_threshold
        conditions['rsi_5m'] = data.rsi_5m < 50
        conditions['rsi_15m'] = data.rsi_15m > 35
        conditions['rsi_1h'] = data.rsi_1h > 50
        conditions['volume_decline'] = data.volume < data.volume_avg
        conditions['weekly_support'] = data.price > data.weekly_support
        
        ema_stack = (data.price > data.ema_20_15m and 
                    data.ema_9_15m > data.ema_21_15m and
                    data.ema_50_daily > data.ema_50_daily * 0.999)
        conditions['ema_stack'] = ema_stack
        conditions['daily_trend'] = data.btc_trend == "UP"
        
        return conditions

    def get_order_book_imbalance(self, symbol: str) -> Optional[float]:
        """Get order book imbalance ratio"""
        try:
            url = "https://api.binance.com/api/v3/depth"
            params = {'symbol': symbol, 'limit': 100}
            response = requests.get(url, params=params, timeout=5)
            
            if response.status_code == 200:
                depth_data = response.json()
                
                total_bid_volume = sum(float(bid[1]) for bid in depth_data['bids'])
                total_ask_volume = sum(float(ask[1]) for ask in depth_data['asks'])
                
                if total_ask_volume > 0:
                    return total_bid_volume / total_ask_volume
                else:
                    return float('inf')
            return None
        except Exception:
            return None

    def calculate_atr_levels(self, data: Dict[str, pd.DataFrame], entry_price: float) -> Dict[str, float]:
        """Calculate ATR-based levels"""
        try:
            df_5m = data['5m'].copy()
            
            df_5m['high_low'] = df_5m['high'] - df_5m['low']
            df_5m['high_close_prev'] = abs(df_5m['high'] - df_5m['close'].shift(1))
            df_5m['low_close_prev'] = abs(df_5m['low'] - df_5m['close'].shift(1))
            df_5m['true_range'] = df_5m[['high_low', 'high_close_prev', 'low_close_prev']].max(axis=1)
            
            atr_14 = df_5m['true_range'].rolling(window=14).mean().iloc[-1]
            
            return {
                'atr': atr_14,
                'stop_loss': entry_price - (0.8 * atr_14),
                'tp1': entry_price + (1.0 * atr_14),
                'tp2': entry_price + (1.8 * atr_14)
            }
        except Exception:
            return {
                'atr': 0,
                'stop_loss': entry_price * 0.99,
                'tp1': entry_price * 1.008,
                'tp2': entry_price * 1.015
            }

    def check_entry_signals(self, symbol: str, data: MarketData, conditions: Dict[str, bool]) -> Optional[Dict]:
        """Check for entry signals"""
        if not all(conditions.values()):
            return None
        
        if symbol in self.position_manager.get_active_symbols():
            return None
            
        current_time = time.time()
        if symbol in self.last_alert_time and current_time - self.last_alert_time[symbol] < 300:
            return None
            
        if len(self.position_manager.get_active_symbols()) >= config.MAX_CONCURRENT_POSITIONS:
            return None
        
        imbalance_ratio = self.get_order_book_imbalance(symbol)
        if imbalance_ratio is None or imbalance_ratio < 1.3:
            return None

        entry_level = 1
        if data.rsi_5m < 40:
            entry_level = 3
        elif data.price <= data.bb_lower * 1.002:
            entry_level = 2
        
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
            'rsi_5m': data.rsi_5m,
            'rsi_15m': data.rsi_15m,
            'rsi_1h': data.rsi_1h,
            'confidence': 95,
            'timestamp': datetime.now().isoformat(),
            'atr_value': atr_levels['atr'],
            'order_book_imbalance': imbalance_ratio,
            'strategy_version': 'v3_terminal'
        }
        
        self.position_manager.add_position(signal)
        
        if self.telegram_notifier:
            self.telegram_notifier.send_signal_alert(signal)
        
        self.last_alert_time[symbol] = current_time
        return signal

    def run_scanner(self):
        """Main scanning loop - updated for 35 coins"""
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
                self.current_data.clear()
                
                for symbol in available_symbols:
                    try:
                        self.current_scanning_symbol = symbol.replace('USDT', '')
                        
                        market_data = self.get_binance_data(symbol)
                        if not market_data or '5m' not in market_data:
                            self.current_data[symbol] = None
                            continue
                            
                        current_data = self.calculate_indicators(market_data)
                        if not current_data:
                            self.current_data[symbol] = None
                            continue
                        
                        self.current_data[symbol] = current_data
                        scanned_count += 1
                        
                        conditions = self.check_strategy_conditions(current_data)
                        conditions_met = sum(conditions.values())
                        
                        signal = self.check_entry_signals(symbol, current_data, conditions)
                        
                        if signal:
                            signals_found += 1
                            coin_name = symbol.replace('USDT', '')
                            self.log_message(f"SIGNAL: {coin_name} LONG ENTRY - Level {signal['entry_level']}", "success")
                            
                            with open('signals.json', 'a') as f:
                                f.write(json.dumps(signal) + '\n')
                        
                        time.sleep(0.2)  # Faster scanning for more coins
                        
                    except Exception as e:
                        self.current_data[symbol] = None
                        continue
                
                self.current_scanning_symbol = None
                self.scan_stats['scan_cycles'] += 1
                self.scan_stats['total_scanned'] = scanned_count
                self.scan_stats['signals_found'] += signals_found
                self.scan_stats['last_scan_time'] = datetime.now()
                
                if signals_found > 0:
                    self.log_message(f"Scan complete: {signals_found} signals from {scanned_count} coins", "success")
                
                time.sleep(12)  # Slightly faster cycles for more coins
                
            except Exception as e:
                self.log_message(f"Scanner error: {e}", "error")
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