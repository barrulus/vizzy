// Keyboard Navigation for Vizzy
// Provides keyboard shortcuts for power users and accessibility

(function() {
    'use strict';

    // Shortcut definitions
    // Keys can be single characters or space-separated sequences (e.g., 'g h')
    const VIZZY_SHORTCUTS = {
        // Navigation
        '/': { action: 'focusSearch', desc: 'Focus search' },
        'Escape': { action: 'escape', desc: 'Close modal / blur input / go back' },
        'g h': { action: 'goHome', desc: 'Go to home' },
        'g e': { action: 'goExplore', desc: 'Go to explore view' },

        // List navigation (vim-style)
        'j': { action: 'nextItem', desc: 'Next item in list' },
        'k': { action: 'prevItem', desc: 'Previous item in list' },
        'ArrowDown': { action: 'nextItem', desc: 'Next item in list' },
        'ArrowUp': { action: 'prevItem', desc: 'Previous item in list' },
        'Enter': { action: 'selectItem', desc: 'Open selected item' },
        'o': { action: 'openInNewTab', desc: 'Open selected in new tab' },

        // Analysis views
        'd': { action: 'viewDuplicates', desc: 'View duplicate packages' },
        'p': { action: 'viewPath', desc: 'Open path finder' },
        'l': { action: 'viewLoops', desc: 'View circular dependencies' },
        'r': { action: 'viewRedundant', desc: 'View redundant links' },
        'w': { action: 'viewWhyChain', desc: 'Why Chain (attribution)' },

        // Graph controls
        '+': { action: 'zoomIn', desc: 'Zoom in graph' },
        '=': { action: 'zoomIn', desc: 'Zoom in graph' },
        '-': { action: 'zoomOut', desc: 'Zoom out graph' },
        '0': { action: 'resetView', desc: 'Reset graph view' },

        // Help
        '?': { action: 'showHelp', desc: 'Show keyboard shortcuts' },
    };

    class KeyboardNav {
        constructor() {
            this.buffer = '';
            this.bufferTimeout = null;
            this.selectedIndex = -1;
            this.navigableItems = [];
            this.helpModalVisible = false;

            this.init();
        }

        init() {
            // Bind keyboard handler
            document.addEventListener('keydown', this.handleKeydown.bind(this));

            // Reset selection when navigable content changes (HTMX)
            document.body.addEventListener('htmx:afterSwap', () => {
                this.resetSelection();
            });

            // Update navigable items on page load
            this.updateNavigableItems();
        }

        handleKeydown(e) {
            // Skip if in input, textarea, or contenteditable
            const target = e.target;
            if (target.matches('input, textarea, select, [contenteditable="true"]')) {
                // Allow Escape to blur inputs
                if (e.key === 'Escape') {
                    e.preventDefault();
                    target.blur();
                }
                return;
            }

            // Handle single special keys that shouldn't go in buffer
            if (e.key === 'Escape') {
                e.preventDefault();
                this.execute('escape');
                return;
            }

            if (e.key === 'Enter') {
                e.preventDefault();
                this.execute('selectItem');
                return;
            }

            if (e.key === 'ArrowDown') {
                e.preventDefault();
                this.execute('nextItem');
                return;
            }

            if (e.key === 'ArrowUp') {
                e.preventDefault();
                this.execute('prevItem');
                return;
            }

            // Build buffer for other keys (single and multi-key shortcuts)
            const key = e.key;

            // Only buffer printable single characters
            if (key.length === 1) {
                this.buffer += key;
                clearTimeout(this.bufferTimeout);

                // Check for exact match first
                const trimmed = this.buffer.trim();
                if (VIZZY_SHORTCUTS[trimmed]) {
                    e.preventDefault();
                    this.execute(VIZZY_SHORTCUTS[trimmed].action);
                    this.buffer = '';
                    return;
                }

                // Check for multi-key sequence match
                const withSpace = this.buffer.replace(/(.)/g, '$1 ').trim();
                if (VIZZY_SHORTCUTS[withSpace]) {
                    e.preventDefault();
                    this.execute(VIZZY_SHORTCUTS[withSpace].action);
                    this.buffer = '';
                    return;
                }

                // Check if buffer could be a prefix of any shortcut
                const couldMatch = Object.keys(VIZZY_SHORTCUTS).some(shortcut => {
                    const normalized = shortcut.replace(/ /g, '');
                    return normalized.startsWith(trimmed);
                });

                if (!couldMatch) {
                    // No possible match, clear buffer
                    this.buffer = '';
                } else {
                    // Reset buffer after timeout
                    this.bufferTimeout = setTimeout(() => {
                        this.buffer = '';
                    }, 800);
                }
            }
        }

        execute(action) {
            switch (action) {
                case 'focusSearch':
                    this.focusSearch();
                    break;

                case 'escape':
                    this.handleEscape();
                    break;

                case 'goHome':
                    window.location.href = '/';
                    break;

                case 'goExplore':
                    this.goToExplore();
                    break;

                case 'nextItem':
                    this.navigateList(1);
                    break;

                case 'prevItem':
                    this.navigateList(-1);
                    break;

                case 'selectItem':
                    this.activateSelected();
                    break;

                case 'openInNewTab':
                    this.openSelectedInNewTab();
                    break;

                case 'viewDuplicates':
                    this.navigateToAnalysis('duplicates');
                    break;

                case 'viewPath':
                    this.navigateToAnalysis('path');
                    break;

                case 'viewLoops':
                    this.navigateToAnalysis('loops');
                    break;

                case 'viewRedundant':
                    this.navigateToAnalysis('redundant');
                    break;

                case 'viewWhyChain':
                    this.navigateToWhyChain();
                    break;

                case 'zoomIn':
                    this.triggerGraphZoom('in');
                    break;

                case 'zoomOut':
                    this.triggerGraphZoom('out');
                    break;

                case 'resetView':
                    this.triggerGraphReset();
                    break;

                case 'showHelp':
                    // Open the main help overlay if available, otherwise keyboard shortcuts
                    if (window.vizzyOnboarding) {
                        window.vizzyOnboarding.toggleHelpOverlay();
                    } else {
                        this.toggleHelpModal();
                    }
                    break;
            }
        }

        focusSearch() {
            const search = document.querySelector('input[type="search"], input[name="q"]');
            if (search) {
                search.focus();
                search.select();
            }
        }

        handleEscape() {
            // Close onboarding help overlay if open
            if (window.vizzyOnboarding && window.vizzyOnboarding.helpOverlayVisible) {
                window.vizzyOnboarding.hideHelpOverlay();
                return;
            }

            // Close tour if active
            if (window.vizzyOnboarding && window.vizzyOnboarding.tourActive) {
                window.vizzyOnboarding.dismissTour();
                return;
            }

            // Close help modal if open
            if (this.helpModalVisible) {
                this.toggleHelpModal();
                return;
            }

            // Close any visible modal
            const modal = document.querySelector('.keyboard-help-modal:not(.hidden), .modal:not(.hidden), .vizzy-help-overlay:not(.hidden)');
            if (modal) {
                modal.classList.add('hidden');
                return;
            }

            // Clear selection
            if (this.selectedIndex >= 0) {
                this.resetSelection();
                return;
            }

            // Go back in history
            if (window.location.pathname !== '/') {
                history.back();
            }
        }

        goToExplore() {
            const importId = this.getCurrentImportId();
            if (importId) {
                window.location.href = `/explore/${importId}`;
            }
        }

        getCurrentImportId() {
            // Try to extract import ID from various URL patterns
            const patterns = [
                /\/explore\/(\d+)/,
                /\/graph\/(?:node|cluster)\/(\d+)/,
                /\/analyze\/\w+\/(\d+)/,
                /\/defined\/(\d+)/,
                /\/module-packages\/(\d+)/,
                /\/visual\/(\d+)/,
                /\/impact\/(\d+)/,
            ];

            for (const pattern of patterns) {
                const match = window.location.pathname.match(pattern);
                if (match) {
                    return match[1];
                }
            }

            // Try to find import ID from page content
            const exploreLink = document.querySelector('a[href^="/explore/"]');
            if (exploreLink) {
                const match = exploreLink.getAttribute('href').match(/\/explore\/(\d+)/);
                if (match) return match[1];
            }

            return null;
        }

        updateNavigableItems() {
            // Find all navigable items on the page
            this.navigableItems = Array.from(document.querySelectorAll([
                // Main content lists
                '.space-y-1 > li > a',
                '.space-y-2 > li > a',
                '.space-y-2 > li:has(a) > a:first-of-type',
                // Search results
                '#search-results a',
                // Package type lists
                'ul.space-y-1 a',
                // Any element marked as navigable
                '[data-navigable]',
            ].join(', ')));
        }

        navigateList(delta) {
            this.updateNavigableItems();

            if (this.navigableItems.length === 0) return;

            // Calculate new index
            let newIndex = this.selectedIndex + delta;
            if (newIndex < 0) newIndex = this.navigableItems.length - 1;
            if (newIndex >= this.navigableItems.length) newIndex = 0;

            // Update selection
            this.selectItem(newIndex);
        }

        selectItem(index) {
            // Remove previous selection
            this.navigableItems.forEach(item => {
                item.classList.remove('keyboard-selected');
            });

            // Set new selection
            this.selectedIndex = index;
            const item = this.navigableItems[index];
            if (item) {
                item.classList.add('keyboard-selected');
                item.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
            }
        }

        resetSelection() {
            this.selectedIndex = -1;
            document.querySelectorAll('.keyboard-selected').forEach(item => {
                item.classList.remove('keyboard-selected');
            });
            this.updateNavigableItems();
        }

        activateSelected() {
            const selected = document.querySelector('.keyboard-selected');
            if (selected) {
                selected.click();
            }
        }

        openSelectedInNewTab() {
            const selected = document.querySelector('.keyboard-selected');
            if (selected && selected.href) {
                window.open(selected.href, '_blank');
            }
        }

        navigateToAnalysis(type) {
            const importId = this.getCurrentImportId();
            if (importId) {
                window.location.href = `/analyze/${type}/${importId}`;
            }
        }

        navigateToWhyChain() {
            // Try to get node ID from current page context
            const nodeId = this.getCurrentNodeId();
            const importId = this.getCurrentImportId();

            if (nodeId && importId) {
                window.location.href = `/analyze/why/${importId}/${nodeId}`;
            } else if (importId) {
                // If on an import page but not a specific node, show a message
                console.log('Why Chain requires a specific node. Navigate to a node first.');
            }
        }

        getCurrentNodeId() {
            // Try to extract node ID from URL patterns
            const patterns = [
                /\/graph\/node\/(\d+)/,
                /\/impact\/(\d+)/,
                /\/visual\/(\d+)/,
            ];

            for (const pattern of patterns) {
                const match = window.location.pathname.match(pattern);
                if (match) {
                    return match[1];
                }
            }

            // Check for why chain URL (extract node_id, the second number)
            const whyMatch = window.location.pathname.match(/\/analyze\/why\/\d+\/(\d+)/);
            if (whyMatch) {
                return whyMatch[1];
            }

            // Try to find selected node on page
            const selectedNode = document.querySelector('[data-node-id].selected, .keyboard-selected[data-node-id]');
            if (selectedNode) {
                return selectedNode.dataset.nodeId;
            }

            return null;
        }

        triggerGraphZoom(direction) {
            // Find active graph container
            const container = document.querySelector('.graph-container');
            if (container && container._graphNavigator) {
                const navigator = container._graphNavigator;
                if (direction === 'in') {
                    navigator.scale = Math.min(5, navigator.scale * 1.2);
                } else {
                    navigator.scale = Math.max(0.1, navigator.scale / 1.2);
                }
                navigator.applyTransform();
            }
        }

        triggerGraphReset() {
            const container = document.querySelector('.graph-container');
            if (container && container._graphNavigator) {
                container._graphNavigator.reset();
            }
        }

        toggleHelpModal() {
            let modal = document.getElementById('keyboard-help-modal');

            if (!modal) {
                modal = this.createHelpModal();
                document.body.appendChild(modal);
            }

            this.helpModalVisible = !this.helpModalVisible;
            modal.classList.toggle('hidden', !this.helpModalVisible);

            if (this.helpModalVisible) {
                // Focus the modal for accessibility
                modal.focus();
            }
        }

        createHelpModal() {
            const modal = document.createElement('div');
            modal.id = 'keyboard-help-modal';
            modal.className = 'keyboard-help-modal hidden';
            modal.setAttribute('role', 'dialog');
            modal.setAttribute('aria-modal', 'true');
            modal.setAttribute('aria-labelledby', 'keyboard-help-title');
            modal.tabIndex = -1;

            // Group shortcuts by category
            const categories = {
                'Navigation': ['/', 'Escape', 'g h', 'g e'],
                'List Navigation': ['j', 'k', 'ArrowDown', 'ArrowUp', 'Enter', 'o'],
                'Analysis Views': ['d', 'p', 'l', 'r', 'w'],
                'Graph Controls': ['+', '-', '0'],
                'Help': ['?'],
            };

            let shortcutsHtml = '';
            for (const [category, keys] of Object.entries(categories)) {
                shortcutsHtml += `<div class="shortcut-category">
                    <h3>${category}</h3>
                    <div class="shortcut-list">`;

                for (const key of keys) {
                    const shortcut = VIZZY_SHORTCUTS[key];
                    if (shortcut) {
                        const displayKey = this.formatKey(key);
                        shortcutsHtml += `
                            <div class="shortcut-item">
                                <span class="shortcut-keys">${displayKey}</span>
                                <span class="shortcut-desc">${shortcut.desc}</span>
                            </div>`;
                    }
                }

                shortcutsHtml += '</div></div>';
            }

            modal.innerHTML = `
                <div class="keyboard-help-backdrop" onclick="document.getElementById('keyboard-help-modal').classList.add('hidden'); window.vizzyKeyboardNav.helpModalVisible = false;"></div>
                <div class="keyboard-help-content">
                    <div class="keyboard-help-header">
                        <h2 id="keyboard-help-title">Keyboard Shortcuts</h2>
                        <button class="keyboard-help-close" onclick="document.getElementById('keyboard-help-modal').classList.add('hidden'); window.vizzyKeyboardNav.helpModalVisible = false;" aria-label="Close">
                            <svg width="20" height="20" viewBox="0 0 20 20" fill="currentColor">
                                <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd"/>
                            </svg>
                        </button>
                    </div>
                    <div class="keyboard-help-body">
                        ${shortcutsHtml}
                    </div>
                    <div class="keyboard-help-footer">
                        <p>Press <kbd>?</kbd> to toggle this help</p>
                    </div>
                </div>
            `;

            return modal;
        }

        formatKey(key) {
            // Format key for display
            const keyMap = {
                'ArrowDown': '<span class="arrow-key">&#x2193;</span>',
                'ArrowUp': '<span class="arrow-key">&#x2191;</span>',
                'Escape': 'Esc',
                'Enter': 'Enter',
            };

            if (keyMap[key]) {
                return `<kbd>${keyMap[key]}</kbd>`;
            }

            // Handle multi-key sequences
            if (key.includes(' ')) {
                return key.split(' ').map(k => `<kbd>${k}</kbd>`).join(' ');
            }

            return `<kbd>${key}</kbd>`;
        }
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            window.vizzyKeyboardNav = new KeyboardNav();
        });
    } else {
        window.vizzyKeyboardNav = new KeyboardNav();
    }
})();
