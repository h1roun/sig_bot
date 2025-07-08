let updateInterval;
let gainersData = [];
let scanningData = {};
let currentFilter = 'all';

// Initialize app
function initApp() {
    console.log('🚀 Initializing app...');
    
    // Load initial data
    loadGainersData().then(() => {
        console.log('✅ Initial data loaded');
    }).catch(error => {
        console.error('❌ Failed to load initial data:', error);
    });
    
    // Start periodic updates
    startUpdates();
    
    // Initialize filters
    initializeFilters();
    
    console.log('✅ App initialization complete');
}

function startBot() {
    const startBtn = document.getElementById('startBtn');
    startBtn.classList.add('loading');
    
    fetch('/api/start', { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            console.log('Scanner started');
            updateBotStatus(true);
            startBtn.classList.remove('loading');
            startScanningProcess();
        })
        .catch(error => {
            console.error('Error starting bot:', error);
            startBtn.classList.remove('loading');
        });
}

function startScanningProcess() {
    console.log('🔍 Starting real scanning process...');
    // The backend will handle the actual scanning
    // Frontend just updates the UI with real data from backend
}

function loadGainersData() {
    const loadingIndicator = document.getElementById('loadingIndicator');
    loadingIndicator.style.display = 'flex';
    
    return fetch('/api/gainers')
        .then(response => response.json())
        .then(data => {
            console.log('📊 Received gainers data:', data);
            gainersData = data.gainers || [];
            console.log(`✅ Loaded ${gainersData.length} gainers`);
            
            if (gainersData.length > 0) {
                renderGainersGrid();
                updateSectionStats();
            } else {
                console.warn('⚠️ No gainers data received');
            }
            
            loadingIndicator.style.display = 'none';
            return gainersData;
        })
        .catch(error => {
            console.error('❌ Error loading gainers:', error);
            loadingIndicator.style.display = 'none';
            
            // Show error state
            const gainersGrid = document.getElementById('gainersGrid');
            gainersGrid.innerHTML = `
                <div class="empty-state" style="grid-column: 1/-1; color: var(--accent-danger);">
                    <div class="empty-icon">❌</div>
                    <p>Error loading market data. Please refresh.</p>
                </div>
            `;
            throw error;
        });
}

function renderGainersGrid(data = gainersData) {
    const gainersGrid = document.getElementById('gainersGrid');
    
    console.log(`🎨 Rendering ${data.length} gainer cards...`);
    
    if (!gainersGrid) {
        console.error('❌ Gainers grid element not found');
        return;
    }
    
    gainersGrid.innerHTML = '';
    
    if (data.length === 0) {
        gainersGrid.innerHTML = `
            <div class="empty-state" style="grid-column: 1/-1;">
                <div class="empty-icon">📊</div>
                <p>Loading top 50 gainers...</p>
            </div>
        `;
        return;
    }
    
    // Sort by conditions met (descending), then by 24h change
    const sortedData = [...data].sort((a, b) => {
        const aScanData = scanningData[a.symbol] || {};
        const bScanData = scanningData[b.symbol] || {};
        const aConditions = aScanData.conditions_met || 0;
        const bConditions = bScanData.conditions_met || 0;
        
        if (aConditions !== bConditions) {
            return bConditions - aConditions; // Sort by conditions met (desc)
        }
        return b.change_24h - a.change_24h; // Then by change (desc)
    });
    
    // Render all 50 coins
    sortedData.forEach((gainer, index) => {
        const scanData = scanningData[gainer.symbol] || {
            scanning: false,
            conditions_met: 0,
            rsi_5m: null,
            volume_ratio: null,
            bb_position: null,
            conditions: {
                bb_touch: false,
                rsi_5m: false,
                rsi_15m: false,
                rsi_1h: false,
                volume_decline: false,
                weekly_support: false,
                ema_stack: false,
                daily_trend: false
            }
        };
        
        const isScanning = scanData.scanning || false;
        const conditionsMet = scanData.conditions_met || 0;
        const conditions = scanData.conditions || {};
        
        const card = document.createElement('div');
        card.className = `gainer-card ${isScanning ? 'scanning' : ''}`;
        card.setAttribute('data-symbol', gainer.symbol);
        
        card.innerHTML = `
            <div class="gainer-header">
                <div class="coin-info">
                    <div class="coin-symbol">${gainer.coin}</div>
                    <div class="coin-price">$${formatPrice(gainer.price)}</div>
                </div>
                <div class="coin-change ${gainer.change_24h < 0 ? 'negative' : ''}">
                    ${gainer.change_24h > 0 ? '+' : ''}${gainer.change_24h.toFixed(2)}%
                </div>
            </div>
            
            <div class="scan-status ${isScanning ? 'scanning' : ''}">
                <div class="status-dot-small"></div>
                <span>${getStatusText(isScanning, conditionsMet)}</span>
            </div>
            
            <div class="conditions-grid-detailed">
                <div class="condition-row ${conditions.bb_touch ? 'met' : 'not-met'}">
                    <div class="condition-indicator"></div>
                    <div class="condition-info">
                        <span class="condition-name">BB Touch</span>
                        <span class="condition-desc">Near lower band</span>
                    </div>
                </div>
                
                <div class="condition-row ${conditions.rsi_5m ? 'met' : 'not-met'}">
                    <div class="condition-indicator"></div>
                    <div class="condition-info">
                        <span class="condition-name">RSI 5m < 50</span>
                        <span class="condition-desc">${scanData.rsi_5m ? scanData.rsi_5m.toFixed(1) : '--'}</span>
                    </div>
                </div>
                
                <div class="condition-row ${conditions.rsi_15m ? 'met' : 'not-met'}">
                    <div class="condition-indicator"></div>
                    <div class="condition-info">
                        <span class="condition-name">RSI 15m > 35</span>
                        <span class="condition-desc">Trend up</span>
                    </div>
                </div>
                
                <div class="condition-row ${conditions.rsi_1h ? 'met' : 'not-met'}">
                    <div class="condition-indicator"></div>
                    <div class="condition-info">
                        <span class="condition-name">RSI 1h > 50</span>
                        <span class="condition-desc">Bullish trend</span>
                    </div>
                </div>
                
                <div class="condition-row ${conditions.volume_decline ? 'met' : 'not-met'}">
                    <div class="condition-indicator"></div>
                    <div class="condition-info">
                        <span class="condition-name">Volume Low</span>
                        <span class="condition-desc">Less selling</span>
                    </div>
                </div>
                
                <div class="condition-row ${conditions.weekly_support ? 'met' : 'not-met'}">
                    <div class="condition-indicator"></div>
                    <div class="condition-info">
                        <span class="condition-name">Above Support</span>
                        <span class="condition-desc">Weekly level</span>
                    </div>
                </div>
                
                <div class="condition-row ${conditions.ema_stack ? 'met' : 'not-met'}">
                    <div class="condition-indicator"></div>
                    <div class="condition-info">
                        <span class="condition-name">EMA Stack</span>
                        <span class="condition-desc">Aligned uptrend</span>
                    </div>
                </div>
                
                <div class="condition-row ${conditions.daily_trend ? 'met' : 'not-met'}">
                    <div class="condition-indicator"></div>
                    <div class="condition-info">
                        <span class="condition-name">Daily Trend</span>
                        <span class="condition-desc">Bullish</span>
                    </div>
                </div>
            </div>
            
            <div class="progress-section">
                <div class="progress-bar">
                    <div class="progress-fill" style="width: ${(conditionsMet / 8) * 100}%"></div>
                </div>
                <div class="progress-text">
                    <span>${conditionsMet}/8 conditions met</span>
                    <span>${conditionsMet === 8 ? '🚨 Signal!' : formatPrice(gainer.volume_usdt, true)}</span>
                </div>
                
                ${scanData.atr_value ? `
                <div class="strategy-indicators">
                    <div class="indicator-row">
                        <span class="indicator-label">ATR:</span>
                        <span class="indicator-value">${scanData.atr_value.toFixed(6)}</span>
                    </div>
                    <div class="indicator-row">
                        <span class="indicator-label">Bid/Ask:</span>
                        <span class="indicator-value ${scanData.order_book_imbalance >= 1.3 ? 'good' : 'poor'}">${scanData.order_book_imbalance ? scanData.order_book_imbalance.toFixed(2) : '--'}:1</span>
                    </div>
                </div>
                ` : ''}
            </div>
        `;
        
        // Add click handler for card interaction
        card.addEventListener('click', () => {
            showCoinDetails(gainer, scanData);
        });
        
        gainersGrid.appendChild(card);
    });
    
    console.log(`✅ Rendered ${sortedData.length} gainer cards`);
}

function getStatusText(scanning, conditionsMet) {
    if (conditionsMet === 8) return 'Signal Generated!';
    if (scanning) return 'Scanning...';
    return `${conditionsMet}/8 conditions`;
}

function formatPrice(price, isVolume = false) {
    if (isVolume) {
        if (price >= 1e9) return (price / 1e9).toFixed(1) + 'B';
        if (price >= 1e6) return (price / 1e6).toFixed(1) + 'M';
        if (price >= 1e3) return (price / 1e3).toFixed(1) + 'K';
        return price.toFixed(0);
    }
    
    if (price < 0.001) return price.toFixed(6);
    if (price < 1) return price.toFixed(4);
    if (price < 100) return price.toFixed(2);
    return price.toFixed(0);
}

function initializeFilters() {
    // Quick filter functionality
    const quickFilters = document.querySelectorAll('.quick-filter');
    quickFilters.forEach(filter => {
        filter.addEventListener('click', function() {
            quickFilters.forEach(f => f.classList.remove('active'));
            this.classList.add('active');
            currentFilter = this.dataset.filter;
            filterAndRenderGainers();
        });
    });
    
    // Search functionality
    const searchInput = document.getElementById('searchInput');
    if (searchInput) {
        searchInput.addEventListener('input', function(e) {
            const searchTerm = e.target.value.toLowerCase();
            filterAndRenderGainers(searchTerm);
        });
    }
    
    // Sort functionality
    const sortFilter = document.getElementById('sortFilter');
    if (sortFilter) {
        sortFilter.addEventListener('change', function(e) {
            sortGainers(e.target.value);
        });
    }
}

function filterAndRenderGainers(searchTerm = '') {
    let filteredData = gainersData.filter(gainer => {
        const matchesSearch = gainer.coin.toLowerCase().includes(searchTerm);
        const scanData = scanningData[gainer.symbol] || {};
        
        switch(currentFilter) {
            case 'scanning':
                return matchesSearch && scanData.scanning;
            case 'signals':
                return matchesSearch && scanData.conditions_met === 8;
            case 'high-change':
                return matchesSearch && gainer.change_24h > 10;
            default:
                return matchesSearch;
        }
    });
    
    renderGainersGrid(filteredData);
    updateSectionStats(filteredData);
}

function sortGainers(sortBy) {
    switch(sortBy) {
        case 'volume':
            gainersData.sort((a, b) => b.volume_usdt - a.volume_usdt);
            break;
        case 'conditions':
            gainersData.sort((a, b) => {
                const aConditions = scanningData[a.symbol]?.conditions_met || 0;
                const bConditions = scanningData[b.symbol]?.conditions_met || 0;
                return bConditions - aConditions;
            });
            break;
        default:
            gainersData.sort((a, b) => b.change_24h - a.change_24h);
    }
    filterAndRenderGainers();
}

function updateSectionStats(data = gainersData) {
    const scanningCount = Object.values(scanningData).filter(s => s.scanning).length;
    const signalsCount = Object.values(scanningData).filter(s => s.conditions_met === 8).length;
    
    const totalCoinsEl = document.getElementById('totalCoins');
    const scanningCountEl = document.getElementById('scanningCount');
    const signalsCountEl = document.getElementById('signalsCount');
    
    if (totalCoinsEl) totalCoinsEl.textContent = data.length;
    if (scanningCountEl) scanningCountEl.textContent = scanningCount;
    if (signalsCountEl) signalsCountEl.textContent = signalsCount;
    
    console.log(`📊 Stats updated: ${data.length} total, ${scanningCount} scanning, ${signalsCount} signals`);
}

function updateBotStatus(running) {
    const statusDot = document.querySelector('.status-dot');
    const statusText = document.getElementById('botStatus');
    
    if (running) {
        statusDot.classList.add('active');
        statusText.textContent = 'Online';
    } else {
        statusDot.classList.remove('active');
        statusText.textContent = 'Offline';
    }
}

function updateStatus() {
    fetch('/api/status')
        .then(response => response.json())
        .then(data => {
            // Update header stats
            document.getElementById('totalSymbols').textContent = data.total_symbols || 0;
            document.getElementById('signalsReady').textContent = data.signals_count || 0;
            document.getElementById('alertCount').textContent = data.alert_count || 0;
            
            // Update bot status
            updateBotStatus(data.running);
            
            // Update scanning progress - shows which coin is being scanned right now
            updateScanningProgress(data.current_scanning);
            
            // Update scanning data from REAL backend scanning
            if (data.top_opportunities && data.top_opportunities.length > 0) {
                data.top_opportunities.forEach(opp => {
                    // Update with REAL scanning data from backend
                    scanningData[opp.symbol] = {
                        scanning: true,
                        conditions_met: opp.conditions_met,
                        rsi_5m: opp.rsi_5m,
                        volume_ratio: 1.5,
                        bb_position: 0.3,
                        conditions: opp.conditions || {
                            bb_touch: false,
                            rsi_5m: false,
                            rsi_15m: false,
                            rsi_1h: false,
                            volume_decline: false,
                            weekly_support: false,
                            ema_stack: false,
                            daily_trend: false
                        }
                    };
                });
                
                // Re-render to show updated data
                renderGainersGrid();
                updateSectionStats();
            }
            
            // Update positions
            if (data.positions) {
                updatePositionsPanel(data.positions);
            }
            
            // Update signals
            updateSignalsPanel(data.alerts || []);
        })
        .catch(error => console.error('Error updating status:', error));
}

function updatePositionsPanel(positions) {
    const positionsStream = document.getElementById('positionsStream');
    const positionCount = document.getElementById('positionCount');
    
    const activePositions = positions.active_positions || [];
    positionCount.textContent = activePositions.length;
    
    // Update trading statistics
    updateTradingStats(positions.statistics || {});
    
    if (activePositions.length === 0) {
        positionsStream.innerHTML = `
            <div class="empty-positions">
                <div class="empty-icon">💼</div>
                <p>No active positions</p>
            </div>
        `;
        return;
    }
    
    positionsStream.innerHTML = '';
    activePositions.forEach(position => {
        const positionCard = document.createElement('div');
        const pnlClass = position.pnl_percent >= 0 ? 'profit' : 'loss';
        const statusClass = position.status.toLowerCase().replace('_', '-');
        
        positionCard.className = `position-card ${pnlClass}`;
        
        // Calculate position progress (based on remaining size)
        const progressPercent = 100 - position.remaining_size;
        
        positionCard.innerHTML = `
            <button class="position-close-btn" onclick="closePosition('${position.symbol}')">✕</button>
            <div class="position-header">
                <div class="position-coin">${position.coin}</div>
                <div class="position-status ${statusClass}">${position.status}</div>
            </div>
            <div class="position-details">
                <div>Entry: $${position.entry_price.toFixed(6)}</div>
                <div>Current: $${position.current_price.toFixed(6)}</div>
                <div>Duration: ${position.duration}</div>
                <div>Size: ${position.remaining_size}%</div>
                ${position.tp1_hit ? '<div>🎯 TP1 Hit</div>' : '<div>Monitoring</div>'}
                ${position.realized_pnl > 0 ? `<div>Banked: +${position.realized_pnl.toFixed(2)}%</div>` : '<div></div>'}
            </div>
            <div class="position-pnl ${pnlClass}">
                ${position.pnl_percent >= 0 ? '+' : ''}${position.pnl_percent.toFixed(2)}%
                ${position.realized_pnl > 0 ? `<br><small>+${position.realized_pnl.toFixed(2)}% banked</small>` : ''}
            </div>
            <div class="position-progress">
                <div class="position-progress-bar">
                    <div class="position-progress-fill" style="width: ${progressPercent}%"></div>
                </div>
                <div class="position-progress-text">${progressPercent}% taken profit</div>
            </div>
        `;
        
        positionsStream.appendChild(positionCard);
    });
}

function updateTradingStats(stats) {
    // Update main stats
    document.getElementById('totalTrades').textContent = stats.total_trades || 0;
    document.getElementById('winRate').textContent = `${(stats.win_rate || 0).toFixed(1)}%`;
    
    const totalPnLElement = document.getElementById('totalPnL');
    const totalPnL = stats.total_pnl || 0;
    totalPnLElement.textContent = `${totalPnL >= 0 ? '+' : ''}${totalPnL.toFixed(2)}%`;
    totalPnLElement.className = `stat-value ${totalPnL >= 0 ? 'success' : 'danger'}`;
    
    document.getElementById('tp1Hits').textContent = stats.tp1_hits || 0;
    document.getElementById('tp2Hits').textContent = stats.tp2_hits || 0;
    document.getElementById('slHits').textContent = stats.sl_hits || 0;
    document.getElementById('breakevenExits').textContent = stats.breakeven_exits || 0;
    
    // Update advanced stats
    const bestTrade = stats.best_trade || 0;
    document.getElementById('bestTrade').textContent = `+${bestTrade.toFixed(2)}%`;
    
    const worstTrade = stats.worst_trade || 0;
    document.getElementById('worstTrade').textContent = `${worstTrade.toFixed(2)}%`;
    
    const profitFactor = stats.profit_factor || 0;
    const profitFactorElement = document.getElementById('profitFactor');
    profitFactorElement.textContent = profitFactor === Infinity ? '∞' : profitFactor.toFixed(2);
    profitFactorElement.className = `value ${profitFactor >= 1.5 ? 'success' : profitFactor >= 1.0 ? 'warning' : 'danger'}`;
}

function testTelegram() {
    fetch('/api/test-telegram', { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                alert('✅ Telegram test message sent!');
            } else {
                alert('❌ Telegram test failed: ' + data.message);
            }
        })
        .catch(error => {
            console.error('Telegram test error:', error);
            alert('❌ Telegram test error');
        });
}

function testBot() {
    const testBtn = document.getElementById('testBtn');
    testBtn.classList.add('loading');
    
    fetch('/api/test-bot', { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            testBtn.classList.remove('loading');
            
            if (data.status === 'success') {
                // Show success message
                showNotification('✅ Bot Test Successful!', data.message, 'success');
                
                // Update UI with test results
                if (data.test_signal) {
                    console.log('Test signal generated:', data.test_signal);
                }
            } else {
                showNotification('❌ Bot Test Failed', data.message, 'error');
            }
        })
        .catch(error => {
            console.error('Bot test error:', error);
            testBtn.classList.remove('loading');
            showNotification('❌ Bot Test Error', 'Failed to connect to bot', 'error');
        });
}

function showNotification(title, message, type = 'info') {
    // Create notification element
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.innerHTML = `
        <div class="notification-content">
            <div class="notification-title">${title}</div>
            <div class="notification-message">${message}</div>
        </div>
        <button class="notification-close" onclick="this.parentElement.remove()">×</button>
    `;
    
    // Add to page
    document.body.appendChild(notification);
    
    // Animate in
    setTimeout(() => notification.classList.add('show'), 100);
    
    // Auto remove after 5 seconds
    setTimeout(() => {
        if (notification.parentElement) {
            notification.classList.remove('show');
            setTimeout(() => notification.remove(), 300);
        }
    }, 5000);
}

function startUpdates() {
    // Start status updates every 3 seconds
    updateInterval = setInterval(updateStatus, 3000);
    console.log('✅ Started status updates');
}

function stopUpdates() {
    if (updateInterval) {
        clearInterval(updateInterval);
        console.log('⏹️ Stopped status updates');
    }
}

function refreshData() {
    console.log('🔄 Refreshing data...');
    loadGainersData();
    updateStatus();
}

function stopBot() {
    const stopBtn = document.getElementById('stopBtn');
    stopBtn.classList.add('loading');
    
    fetch('/api/stop', { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            console.log('Scanner stopped');
            updateBotStatus(false);
            stopBtn.classList.remove('loading');
        })
        .catch(error => {
            console.error('Error stopping bot:', error);
            stopBtn.classList.remove('loading');
        });
}

function updateScanningProgress(currentCoin) {
    const scanningProgress = document.getElementById('scanningProgress');
    const currentScanningCoin = document.getElementById('currentScanningCoin');
    
    if (currentCoin) {
        // Show scanning progress
        scanningProgress.style.display = 'block';
        currentScanningCoin.textContent = currentCoin;
        console.log(`🔍 Currently scanning: ${currentCoin}`);
    } else {
        // Hide scanning progress when not scanning
        scanningProgress.style.display = 'none';
    }
}

function updateSignalsPanel(alerts) {
    const signalsStream = document.getElementById('signalsStream');
    const signalCount = document.getElementById('signalCount');
    
    // Update signal count
    const signalAlerts = alerts.filter(alert => alert.type === 'SIGNAL');
    signalCount.textContent = signalAlerts.length;
    
    if (alerts.length === 0) {
        signalsStream.innerHTML = `
            <div class="empty-signals">
                <div class="empty-icon">📡</div>
                <p>Waiting for trading signals...</p>
            </div>
        `;
        return;
    }
    
    signalsStream.innerHTML = '';
    alerts.forEach(alert => {
        const signalCard = document.createElement('div');
        signalCard.className = 'signal-card';
        
        let cardClass = 'signal-card';
        if (alert.type === 'SIGNAL') cardClass += ' signal-active';
        if (alert.type === 'TEST') cardClass += ' signal-test';
        
        signalCard.className = cardClass;
        signalCard.innerHTML = `
            <div class="signal-header">
                <div class="signal-coin">${getSignalIcon(alert.type)} ${alert.message}</div>
                <div class="signal-time">${alert.time}</div>
            </div>
            <div class="signal-details">${alert.details}</div>
        `;
        
        signalsStream.appendChild(signalCard);
    });
}

function getSignalIcon(type) {
    switch(type) {
        case 'SIGNAL': return '🚨';
        case 'TEST': return '🧪';
        case 'INFO': return 'ℹ️';
        default: return '📢';
    }
}

function showCoinDetails(gainer, scanData) {
    console.log('Coin details:', gainer.coin, scanData);
    // Could implement a modal or detailed view here
}

function renderFilteredGainers(filteredData) {
    renderGainersGrid(filteredData);
    updateSectionStats(filteredData);
}

// Event listeners and initialization
document.addEventListener('DOMContentLoaded', function() {
    const searchInput = document.getElementById('searchInput');
    if (searchInput) {
        searchInput.addEventListener('input', function(e) {
            const searchTerm = e.target.value.toLowerCase();
            const filteredGainers = gainersData.filter(gainer => 
                gainer.coin.toLowerCase().includes(searchTerm)
            );
            renderFilteredGainers(filteredGainers);
        });
    }
    
    // Initialize app
    initApp();
});

// Auto-start when page loads
window.onload = function() {
    console.log('🌐 Page loaded, initializing...');
    // Don't auto-start the bot, let user click start button
    console.log('💡 Click "Start Scanner" to begin');
};

// Cleanup on page unload
window.onbeforeunload = function() {
    stopUpdates();
};

function closePosition(symbol) {
    if (!confirm(`Close position for ${symbol.replace('USDT', '')}?`)) {
        return;
    }
    
    fetch('/api/close-position', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ symbol: symbol })
    })
    .then(response => response.json())
    .then(data => {
        if (data.status === 'success') {
            console.log('Position closed:', symbol);
            updateStatus(); // Refresh positions
        } else {
            console.error('Failed to close position:', data.message);
        }
    })
    .catch(error => {
        console.error('Error closing position:', error);
    });
}
