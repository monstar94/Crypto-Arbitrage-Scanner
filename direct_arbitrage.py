import sys
import time
import json
import requests
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QDialog, QTextEdit, QStyleFactory, QCheckBox, QGridLayout
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPalette, QColor, QFont

class DirectArbitrage:
    def __init__(self):
        self.sessions = {}
        self.last_prices = {}
        self.last_update = {}
        self.cache_duration = 10  # Cache duration in seconds
        self.min_profit_percent = 0.5  # Minimum profit percentage
        self.investment = 100  # $1000 investment
        
        # Define exchange API endpoints and configurations
        self.exchanges = {
            'Binance': {
                'url': 'https://api.binance.com/api/v3/ticker/bookTicker',
                'fee': 0.075  # 0.075% with BNB
            },
            'KuCoin': {
                'url': 'https://api.kucoin.com/api/v1/market/allTickers',
                'fee': 0.08  # 0.08% with KCS
            },
            'MEXC': {
                'url': 'https://api.mexc.com/api/v3/ticker/price',
                'fee': 0.2
            },
            'Bybit': {
                'url': 'https://api.bybit.com/v5/market/tickers?category=spot',
                'fee': 0.06  # 0.06% with BIT
            },
            'OKX': {
                'url': 'https://www.okx.com/api/v5/market/tickers?instType=SPOT',
                'fee': 0.08  # 0.08% with OKB
            },
            'LBank': {
                'url': 'https://api.lbkex.com/v1/ticker.do?symbol=all',
                'fee': 0.08  # 0.08% standard fee
            },
            'Bitget': {
                'url': 'https://api.bitget.com/api/spot/v1/market/tickers',
                'fee': 0.1  # 0.1% standard fee
            }
        }
        
        # Initialize sessions
        self.sessions = {
            exchange: requests.Session() for exchange in self.exchanges.keys()
        }
        
        self.quote_currencies = [
            'USDT', 'USDC', 'BUSD', 'DAI', 'TUSD', 'USDP', 
            'USDD', 'FDUSD', 'PYUSD', 'EURC', 'EUROC'
        ]
        
    def is_valid_price(self, price):
        """Validate price values"""
        try:
            price = float(price)
            return price > 0 and price < 1000000  # Reasonable price range
        except (TypeError, ValueError):
            return False

    def is_realistic_price_difference(self, price1, price2):
        """Check if the price difference between exchanges is realistic"""
        if not (self.is_valid_price(price1) and self.is_valid_price(price2)):
            return False
            
        # Calculate percentage difference
        avg_price = (price1 + price2) / 2
        diff_percent = abs(price1 - price2) / avg_price * 100
        
        # Max 3% difference between exchanges for major pairs
        return diff_percent <= 3

    def normalize_pair(self, pair):
        """Normalize trading pair format across exchanges"""
        # Remove common separators and convert to uppercase
        pair = pair.upper().replace('-', '').replace('_', '').replace('/', '')
        
        # Handle special cases for each exchange
        if 'USDT' in pair:
            # Ensure USDT pairs are properly formatted
            if not pair.endswith('USDT'):
                # Move USDT to end if it's in the middle
                pair = pair.replace('USDT', '') + 'USDT'
        return pair

    def get_exchange_prices(self):
        """Get prices from all exchanges with normalized pair formats and validation"""
        all_prices = {}
        
        for exchange, api in self.exchanges.items():
            try:
                response = requests.get(api['url'])
                response.raise_for_status()
                data = response.json()
                prices = {}
                
                if exchange == 'Binance':
                    for ticker in data:
                        try:
                            if not all(k in ticker for k in ['symbol', 'bidPrice', 'askPrice']):
                                continue
                                
                            bid = float(ticker['bidPrice'])
                            ask = float(ticker['askPrice'])
                            
                            if not (self.is_valid_price(bid) and self.is_valid_price(ask)):
                                continue
                                
                            # Max 1% spread between bid and ask
                            if bid >= ask or (ask - bid) / bid > 0.01:
                                continue
                                
                            pair = self.normalize_pair(ticker['symbol'])
                            prices[pair] = {
                                'bid': bid,
                                'ask': ask,
                                'original_symbol': ticker['symbol']
                            }
                        except (KeyError, ValueError, TypeError) as e:
                            continue
                
                elif exchange == 'KuCoin':
                    if 'data' in data and 'ticker' in data['data']:
                        for ticker in data['data']['ticker']:
                            try:
                                if not all(k in ticker for k in ['symbol', 'buy', 'sell']):
                                    continue
                                    
                                bid = float(ticker['buy'])
                                ask = float(ticker['sell'])
                                
                                if not (self.is_valid_price(bid) and self.is_valid_price(ask)):
                                    continue
                                    
                                # Max 1% spread between bid and ask
                                if bid >= ask or (ask - bid) / bid > 0.01:
                                    continue
                                    
                                pair = self.normalize_pair(ticker['symbol'])
                                prices[pair] = {
                                    'bid': bid,
                                    'ask': ask,
                                    'original_symbol': ticker['symbol']
                                }
                            except (KeyError, ValueError, TypeError) as e:
                                continue
                
                elif exchange == 'MEXC':
                    try:
                        # First get all symbols with their prices
                        prices_response = requests.get(api['url'])
                        prices_response.raise_for_status()
                        prices_data = prices_response.json()
                        
                        # Then get the order book data for bid/ask
                        book_url = 'https://api.mexc.com/api/v3/ticker/bookTicker'
                        book_response = requests.get(book_url)
                        book_response.raise_for_status()
                        book_data = book_response.json()
                        
                        # Create a map of symbol to book data for faster lookup
                        book_map = {item['symbol']: item for item in book_data}
                        
                        for price_item in prices_data:
                            try:
                                symbol = price_item['symbol']
                                if symbol not in book_map:
                                    continue
                                    
                                book_item = book_map[symbol]
                                if not all(k in book_item for k in ['bidPrice', 'askPrice']):
                                    continue
                                    
                                bid = float(book_item['bidPrice'])
                                ask = float(book_item['askPrice'])
                                
                                if not (self.is_valid_price(bid) and self.is_valid_price(ask)):
                                    continue
                                    
                                # Max 1% spread between bid and ask
                                if bid >= ask or (ask - bid) / bid > 0.01:
                                    continue
                                    
                                pair = self.normalize_pair(symbol)
                                prices[pair] = {
                                    'bid': bid,
                                    'ask': ask,
                                    'original_symbol': symbol
                                }
                            except (KeyError, ValueError, TypeError) as e:
                                continue
                    except Exception as e:
                        print(f"Error fetching MEXC data: {str(e)}")
                
                elif exchange == 'Bybit':
                    if 'result' in data and 'list' in data['result']:
                        for ticker in data['result']['list']:
                            try:
                                if not all(k in ticker for k in ['symbol', 'bid1Price', 'ask1Price']):
                                    continue
                                    
                                bid = float(ticker['bid1Price'])
                                ask = float(ticker['ask1Price'])
                                
                                if not (self.is_valid_price(bid) and self.is_valid_price(ask)):
                                    continue
                                    
                                # Max 1% spread between bid and ask
                                if bid >= ask or (ask - bid) / bid > 0.01:
                                    continue
                                    
                                pair = self.normalize_pair(ticker['symbol'])
                                prices[pair] = {
                                    'bid': bid,
                                    'ask': ask,
                                    'original_symbol': ticker['symbol']
                                }
                            except (KeyError, ValueError, TypeError) as e:
                                continue
                
                elif exchange == 'OKX':
                    if 'data' in data:
                        for ticker in data['data']:
                            try:
                                if not all(k in ticker for k in ['instId', 'bidPx', 'askPx']):
                                    continue
                                    
                                bid = float(ticker['bidPx'])
                                ask = float(ticker['askPx'])
                                
                                if not (self.is_valid_price(bid) and self.is_valid_price(ask)):
                                    continue
                                    
                                # Max 1% spread between bid and ask
                                if bid >= ask or (ask - bid) / bid > 0.01:
                                    continue
                                    
                                pair = self.normalize_pair(ticker['instId'])
                                prices[pair] = {
                                    'bid': bid,
                                    'ask': ask,
                                    'original_symbol': ticker['instId']
                                }
                            except (KeyError, ValueError, TypeError) as e:
                                continue
                
                elif exchange == 'LBank':
                    for ticker in data:
                        try:
                            if 'symbol' not in ticker or 'ticker' not in ticker:
                                continue
                                
                            if 'bid' in ticker['ticker'] and 'ask' in ticker['ticker']:
                                bid = float(ticker['ticker']['bid'])
                                ask = float(ticker['ticker']['ask'])
                            else:
                                latest = float(ticker['ticker']['latest'])
                                bid = latest * 0.999  # 0.1% spread
                                ask = latest * 1.001
                            
                            if not (self.is_valid_price(bid) and self.is_valid_price(ask)):
                                continue
                                
                            # Max 1% spread between bid and ask
                            if bid >= ask or (ask - bid) / bid > 0.01:
                                continue
                                
                            pair = self.normalize_pair(ticker['symbol'])
                            prices[pair] = {
                                'bid': bid,
                                'ask': ask,
                                'original_symbol': ticker['symbol']
                            }
                        except (KeyError, ValueError, TypeError) as e:
                            continue
                
                elif exchange == 'Bitget':
                    if 'data' in data:
                        for ticker in data['data']:
                            try:
                                if not all(k in ticker for k in ['symbol', 'buyOne', 'sellOne']):
                                    continue
                                    
                                bid = float(ticker['buyOne'])
                                ask = float(ticker['sellOne'])
                                
                                if not (self.is_valid_price(bid) and self.is_valid_price(ask)):
                                    continue
                                    
                                # Max 1% spread between bid and ask
                                if bid >= ask or (ask - bid) / bid > 0.01:
                                    continue
                                    
                                # Bitget uses USDT suffix, normalize it
                                pair = self.normalize_pair(ticker['symbol'])
                                prices[pair] = {
                                    'bid': bid,
                                    'ask': ask,
                                    'original_symbol': ticker['symbol']
                                }
                            except (KeyError, ValueError, TypeError) as e:
                                continue
                
                all_prices[exchange] = prices
                print(f"Found {len(prices)} valid pairs on {exchange}")
                
            except Exception as e:
                print(f"Error fetching prices from {exchange}: {str(e)}")
                all_prices[exchange] = {}
        
        return all_prices

    def find_arbitrage_opportunities(self):
        """Find arbitrage opportunities with exact pair matching"""
        opportunities = []
        prices = self.get_exchange_prices()
        
        # Get all unique normalized pairs across all exchanges
        all_pairs = set()
        for exchange_prices in prices.values():
            all_pairs.update(exchange_prices.keys())
        
        # For each pair, compare prices across exchanges
        for pair in all_pairs:
            # Get all exchanges that have this exact pair
            exchanges_with_pair = [
                exchange for exchange, exchange_prices in prices.items()
                if pair in exchange_prices
            ]
            
            # Need at least 2 exchanges to compare
            if len(exchanges_with_pair) < 2:
                continue
            
            # Compare each exchange combination for this pair
            for buy_exchange in exchanges_with_pair:
                buy_data = prices[buy_exchange][pair]
                
                for sell_exchange in exchanges_with_pair:
                    if buy_exchange == sell_exchange:
                        continue
                        
                    sell_data = prices[sell_exchange][pair]
                    
                    # Get prices
                    buy_price = buy_data['ask']   # Price to buy
                    sell_price = sell_data['bid'] # Price to sell
                    
                    # Skip if prices are invalid or unrealistic
                    if not self.is_realistic_price_difference(buy_price, sell_price):
                        continue
                    
                    # Calculate profit with fees
                    buy_fee = self.exchanges[buy_exchange].get('fee', 0.1) / 100
                    sell_fee = self.exchanges[sell_exchange].get('fee', 0.1) / 100
                    
                    # Calculate amounts with fees
                    buy_amount = self.investment * (1 + buy_fee)
                    coins_bought = (self.investment / buy_price) * (1 - buy_fee)
                    sell_amount = (coins_bought * sell_price) * (1 - sell_fee)
                    
                    profit_amount = sell_amount - buy_amount
                    profit_percent = (profit_amount / buy_amount) * 100
                    
                    # Only show opportunities with realistic profits (max 3%)
                    if 0 < profit_percent <= 3:
                        # Format pair for display
                        display_pair = pair
                        for quote in self.quote_currencies:
                            if pair.endswith(quote):
                                base = pair[:-len(quote)]
                                display_pair = f"{base}/{quote}"
                                break
                        
                        opportunities.append({
                            'pair': display_pair,
                            'buy_exchange': buy_exchange,
                            'sell_exchange': sell_exchange,
                            'buy_price': buy_price,
                            'sell_price': sell_price,
                            'profit_percent': profit_percent,
                            'profit_amount': profit_amount,
                            'investment': self.investment,
                            'original_buy_symbol': buy_data['original_symbol'],
                            'original_sell_symbol': sell_data['original_symbol'],
                            'buy_fee': buy_fee * 100,
                            'sell_fee': sell_fee * 100,
                            'coins_bought': coins_bought,
                            'final_amount': sell_amount
                        })
        
        # Sort by profit percentage
        opportunities.sort(key=lambda x: x['profit_percent'], reverse=True)
        return opportunities

class DirectArbitrageGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.arbitrage = DirectArbitrage()
        self.opportunities = []
        self.min_profit_percent = 0.5  # Minimum profit percentage to show
        self.selected_exchanges = set(self.arbitrage.exchanges.keys())  # All exchanges selected by default
        self.init_ui()

    def init_ui(self):
        """Initialize the user interface"""
        self.setWindowTitle('Crypto Arbitrage')
        self.setGeometry(100, 100, 1400, 800)
        
        # Create main widget and layout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        layout.setSpacing(15)
        layout.setContentsMargins(15, 15, 15, 15)
        
        # Create top panel
        top_panel = QWidget()
        top_panel.setStyleSheet("""
            QWidget {
                background-color: #1E1E1E;
                border-radius: 6px;
            }
        """)
        top_panel.setFixedHeight(50)  # Fixed height for consistency
        
        top_layout = QHBoxLayout(top_panel)
        top_layout.setContentsMargins(15, 0, 15, 0)
        top_layout.setSpacing(15)
        
        # Left side - inputs
        inputs_widget = QWidget()
        inputs_layout = QHBoxLayout(inputs_widget)
        inputs_layout.setSpacing(10)
        inputs_layout.setContentsMargins(0, 0, 0, 0)
        
        self.investment_input = QLineEdit()
        self.investment_input.setPlaceholderText('Investment $')
        self.investment_input.setText('1000')
        self.investment_input.setFixedWidth(120)
        self.investment_input.setFixedHeight(32)
        
        self.profit_input = QLineEdit()
        self.profit_input.setPlaceholderText('Min Profit %')
        self.profit_input.setText('0.5')
        self.profit_input.setFixedWidth(120)
        self.profit_input.setFixedHeight(32)
        
        inputs_layout.addWidget(self.investment_input)
        inputs_layout.addWidget(self.profit_input)
        
        # Center - exchanges in horizontal layout
        exchanges_widget = QWidget()
        exchanges_layout = QHBoxLayout(exchanges_widget)
        exchanges_layout.setSpacing(15)
        exchanges_layout.setContentsMargins(0, 0, 0, 0)
        
        self.exchange_checkboxes = {}
        for exchange in self.arbitrage.exchanges.keys():
            checkbox = QCheckBox(exchange)
            checkbox.setChecked(True)
            checkbox.stateChanged.connect(self.update_selected_exchanges)
            self.exchange_checkboxes[exchange] = checkbox
            exchanges_layout.addWidget(checkbox)
        
        # Right side - buttons
        buttons_widget = QWidget()
        buttons_layout = QHBoxLayout(buttons_widget)
        buttons_layout.setSpacing(8)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        
        self.start_btn = QPushButton('▶ Start')
        self.start_btn.clicked.connect(self.start_monitoring)
        self.start_btn.setFixedWidth(90)
        self.start_btn.setFixedHeight(32)
        
        self.refresh_btn = QPushButton('↻ Refresh')
        self.refresh_btn.clicked.connect(self.refresh_data)
        self.refresh_btn.setFixedWidth(90)
        self.refresh_btn.setFixedHeight(32)
        
        buttons_layout.addWidget(self.start_btn)
        buttons_layout.addWidget(self.refresh_btn)
        
        # Add widgets to top layout with proper spacing
        top_layout.addWidget(inputs_widget)
        top_layout.addStretch(1)
        top_layout.addWidget(exchanges_widget)
        top_layout.addStretch(1)
        top_layout.addWidget(buttons_widget)
        
        # Create table
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            'Trading Pair', 'Buy From', 'Sell At', 
            'Buy Price', 'Sell Price', 'Profit %',
            'Profit $', 'Investment'
        ])
        
        # Set table properties
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft)
        header.setFixedHeight(35)
        header.setStyleSheet("""
            QHeaderView::section {
                background-color: #1E1E1E;
                color: #888888;
                border: none;
                border-bottom: 1px solid #333333;
                padding: 5px 10px;
                font-size: 12px;
                font-weight: bold;
            }
            QHeaderView::section:first {
                padding-left: 15px;
            }
            QHeaderView::section:nth-child(6),
            QHeaderView::section:nth-child(7) {
                color: #4CAF50;
            }
        """)
        
        # Set table style
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #121212;
                color: white;
                border: none;
                border-radius: 6px;
                gridline-color: #2A2A2A;
                outline: none;
            }
            QTableWidget::item {
                padding: 8px 10px;
                border-bottom: 1px solid #1E1E1E;
            }
            QTableWidget::item:first {
                padding-left: 15px;
            }
            QTableWidget::item:selected {
                background-color: #2A2A2A;
            }
        """)
        
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        self.table.setVerticalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        self.table.horizontalHeader().setStretchLastSection(True)
        
        # Add widgets to main layout
        layout.addWidget(top_panel)
        layout.addWidget(self.table)
        
        # Update styles
        self.setStyleSheet("""
            QMainWindow {
                background-color: #121212;
            }
            QLineEdit {
                background-color: #252525;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 4px 12px;
                font-size: 13px;
                font-weight: bold;
            }
            QLineEdit::placeholder {
                color: #888888;
            }
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
            QCheckBox {
                color: white;
                spacing: 8px;
                font-size: 13px;
                font-weight: bold;
                padding: 0px 4px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 3px;
                border: 2px solid #4CAF50;
            }
            QCheckBox::indicator:unchecked {
                background-color: transparent;
            }
            QCheckBox::indicator:checked {
                background-color: #4CAF50;
                border-color: #4CAF50;
                image: url(check.png);
            }
        """)
        
        self.statusBar().showMessage('Ready')

    def update_selected_exchanges(self):
        """Update the set of selected exchanges based on checkbox states"""
        self.selected_exchanges = {
            exchange for exchange, checkbox in self.exchange_checkboxes.items()
            if checkbox.isChecked()
        }

    def refresh_data(self):
        """Refresh arbitrage opportunities"""
        try:
            # Update investment amount
            investment = float(self.investment_input.text())
            self.arbitrage.investment = investment
            
            # Update minimum profit
            self.min_profit_percent = float(self.profit_input.text())
            
            # Get opportunities
            self.statusBar().showMessage('Fetching latest prices...')
            all_opportunities = self.arbitrage.find_arbitrage_opportunities()
            
            # Filter opportunities by selected exchanges and minimum profit
            self.opportunities = [
                op for op in all_opportunities
                if op['buy_exchange'] in self.selected_exchanges
                and op['sell_exchange'] in self.selected_exchanges
                and op['profit_percent'] >= self.min_profit_percent
            ]
            
            self.update_table()
            
            if len(self.opportunities) > 0:
                best_op = self.opportunities[0]
                self.statusBar().showMessage(
                    f"Found {len(self.opportunities)} opportunities. " +
                    f"Best: {best_op['pair']} ({best_op['buy_exchange']} → {best_op['sell_exchange']}) {best_op['profit_percent']:.2f}%"
                )
            else:
                self.statusBar().showMessage('No profitable opportunities found')
                
        except ValueError as e:
            self.statusBar().showMessage('Invalid input values')
        except Exception as e:
            self.statusBar().showMessage(f'Error: {str(e)}')

    def show_detailed_analysis(self, item):
        """Show detailed analysis of the selected opportunity"""
        row = item.row()
        if row < len(self.opportunities):
            op = self.opportunities[row]
            
            dialog = QDialog(self)
            dialog.setWindowTitle(f"Detailed Analysis - {op['pair']}")
            dialog.setMinimumWidth(600)
            dialog.setStyleSheet("""
                QDialog {
                    background-color: #1e1e1e;
                }
                QTextEdit {
                    background-color: #2d2d2d;
                    color: #ffffff;
                    border: none;
                    border-radius: 8px;
                    padding: 15px;
                    selection-background-color: #2962ff;
                }
            """)
            
            layout = QVBoxLayout(dialog)
            layout.setContentsMargins(20, 20, 20, 20)
            layout.setSpacing(15)
            
            # Create title
            title = QLabel(f"Trading Analysis for {op['pair']}")
            title.setStyleSheet("""
                font-size: 18px;
                font-weight: bold;
                color: #ffffff;
                padding-bottom: 10px;
            """)
            layout.addWidget(title)
            
            # Create details with HTML formatting
            details = f"""
            <style>
                .detail-table {{ 
                    border-collapse: collapse; 
                    width: 100%;
                    margin: 10px 0;
                }}
                .detail-table td, .detail-table th {{ 
                    padding: 12px; 
                    text-align: left; 
                    border-bottom: 1px solid #3d3d3d;
                }}
                .section-header {{
                    color: #888888;
                    font-size: 14px;
                    font-weight: bold;
                    padding: 15px 12px 5px 12px;
                    background-color: #2d2d2d;
                }}
                .label {{
                    color: #888888;
                    width: 140px;
                }}
                .value {{
                    color: #ffffff;
                    font-weight: 500;
                }}
                .profit {{
                    color: #00c853;
                    font-weight: bold;
                }}
                .fee {{
                    color: #ff5252;
                }}
                .exchange {{
                    color: #ffb74d;
                }}
                .pair {{
                    color: #42a5f5;
                }}
            </style>
            
            <div class='section-header'>TRADING PAIR INFORMATION</div>
            <table class='detail-table'>
                <tr>
                    <td class='label'>Trading Pair:</td>
                    <td class='value pair'>{op['pair']}</td>
                </tr>
                <tr>
                    <td class='label'>Buy Exchange:</td>
                    <td class='value exchange'>{op['buy_exchange']} ({op['original_buy_symbol']})</td>
                </tr>
                <tr>
                    <td class='label'>Sell Exchange:</td>
                    <td class='value exchange'>{op['sell_exchange']} ({op['original_sell_symbol']})</td>
                </tr>
            </table>

            <div class='section-header'>PRICE INFORMATION</div>
            <table class='detail-table'>
                <tr>
                    <td class='label'>Buy Price:</td>
                    <td class='value'>${op['buy_price']:.8f}</td>
                </tr>
                <tr>
                    <td class='label'>Sell Price:</td>
                    <td class='value'>${op['sell_price']:.8f}</td>
                </tr>
                <tr>
                    <td class='label'>Buy Fee:</td>
                    <td class='value fee'>{op['buy_fee']:.2f}%</td>
                </tr>
                <tr>
                    <td class='label'>Sell Fee:</td>
                    <td class='value fee'>{op['sell_fee']:.2f}%</td>
                </tr>
            </table>

            <div class='section-header'>PROFIT ANALYSIS</div>
            <table class='detail-table'>
                <tr>
                    <td class='label'>Investment:</td>
                    <td class='value'>${op['investment']:.2f}</td>
                </tr>
                <tr>
                    <td class='label'>Coins Bought:</td>
                    <td class='value'>{op['coins_bought']:.8f}</td>
                </tr>
                <tr>
                    <td class='label'>Final Amount:</td>
                    <td class='value'>${op['final_amount']:.2f}</td>
                </tr>
                <tr>
                    <td class='label'>Profit Amount:</td>
                    <td class='value profit'>${op['profit_amount']:.2f}</td>
                </tr>
                <tr>
                    <td class='label'>Profit Percentage:</td>
                    <td class='value profit'>{op['profit_percent']:.2f}%</td>
                </tr>
            </table>
            """
            
            # Create text display
            text_display = QTextEdit()
            text_display.setHtml(details)
            text_display.setReadOnly(True)
            layout.addWidget(text_display)
            
            dialog.exec()

    def update_table(self):
        """Update the table with current opportunities"""
        self.table.setRowCount(len(self.opportunities))
        
        for i, op in enumerate(self.opportunities):
            # Format values
            pair = op['pair'].replace('/', '-')
            buy_exchange = op['buy_exchange']
            sell_exchange = op['sell_exchange']
            buy_price = f"${op['buy_price']:.8f}"
            sell_price = f"${op['sell_price']:.8f}"
            profit_percent = f"{op['profit_percent']:.2f}%"
            profit_amount = f"${op['profit_amount']:.2f}"
            investment = f"${op['investment']:.2f}"
            
            # Create items
            items = [
                self.create_table_item(pair, 'pair'),
                self.create_table_item(buy_exchange, 'exchange'),
                self.create_table_item(sell_exchange, 'exchange'),
                self.create_table_item(buy_price, 'price'),
                self.create_table_item(sell_price, 'price'),
                self.create_table_item(profit_percent, 'profit'),
                self.create_table_item(profit_amount, 'profit'),
                self.create_table_item(investment, 'investment')
            ]
            
            # Add items to table
            for col, item in enumerate(items):
                self.table.setItem(i, col, item)
            
            # Set row height
            self.table.setRowHeight(i, 40)
    
    def create_table_item(self, text, item_type):
        """Create a table item with appropriate styling"""
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        
        # Set colors based on item type
        if item_type == 'profit':
            item.setForeground(QColor("#4CAF50"))  # Brighter green for profit
            font = item.font()
            font.setBold(True)
            item.setFont(font)
        elif item_type == 'exchange':
            item.setForeground(QColor("#64B5F6"))  # Light blue for exchanges
        elif item_type == 'pair':
            item.setForeground(QColor("#FFA726"))  # Orange for trading pairs
        elif item_type == 'price':
            item.setForeground(QColor("#E0E0E0"))  # Light gray for prices
        else:
            item.setForeground(QColor("#FFFFFF"))  # White for other items
        
        return item

    def start_monitoring(self):
        """Start continuous monitoring of arbitrage opportunities"""
        self.refresh_data()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = DirectArbitrageGUI()
    ex.show()
    sys.exit(app.exec())
