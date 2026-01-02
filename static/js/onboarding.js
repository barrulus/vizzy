// Vizzy Onboarding and Help System
// Provides first-time user tour, contextual help tooltips, and feature discovery hints

(function() {
    'use strict';

    // Storage keys
    const STORAGE_PREFIX = 'vizzy_onboarding_';
    const STORAGE_KEYS = {
        tourCompleted: STORAGE_PREFIX + 'tour_completed',
        tourDismissed: STORAGE_PREFIX + 'tour_dismissed',
        tipsEnabled: STORAGE_PREFIX + 'tips_enabled',
        dismissedTips: STORAGE_PREFIX + 'dismissed_tips',
        seenFeatures: STORAGE_PREFIX + 'seen_features',
        helpShownCount: STORAGE_PREFIX + 'help_shown_count'
    };

    // Tour step definitions
    const TOUR_STEPS = [
        {
            id: 'welcome',
            title: 'Welcome to Vizzy',
            content: 'Vizzy helps you explore and understand NixOS derivation dependency graphs. Let me show you around.',
            target: null, // No target, centered modal
            position: 'center'
        },
        {
            id: 'navigation',
            title: 'Navigation',
            content: 'Use the top navigation bar to move between Home, Compare configurations, and Baselines. The current view context is shown when exploring an import.',
            target: '.nav-primary',
            position: 'bottom'
        },
        {
            id: 'search',
            title: 'Search Packages',
            content: 'Press "/" to quickly search for any package in the current configuration. Results appear instantly as you type.',
            target: '.nav-search',
            position: 'bottom'
        },
        {
            id: 'keyboard',
            title: 'Keyboard Shortcuts',
            content: 'Press "?" at any time to see all available keyboard shortcuts. Power users can navigate entirely with the keyboard.',
            target: '.nav-help-btn',
            position: 'bottom-start'
        },
        {
            id: 'graph',
            title: 'Graph Exploration',
            content: 'Click and drag to pan the graph. Scroll to zoom. Click any node to see its details and dependencies.',
            target: '.graph-container',
            position: 'top'
        },
        {
            id: 'analysis',
            title: 'Analysis Tools',
            content: 'Use analysis tools to find duplicates (d), paths (p), circular dependencies (l), and redundant links (r). Press the key in parentheses for quick access.',
            target: '[href*="/analyze/"]',
            targetFallback: '.lg\\:col-span-1',
            position: 'right'
        },
        {
            id: 'whychain',
            title: 'Why Chain',
            content: 'The "Why Chain" (w) shows you exactly why a package is in your closure and what top-level packages require it.',
            target: '[href*="/analyze/why/"]',
            targetFallback: null,
            position: 'right'
        },
        {
            id: 'complete',
            title: 'You\'re Ready!',
            content: 'That covers the basics. Explore your NixOS configuration and discover optimization opportunities. You can replay this tour from the help menu.',
            target: null,
            position: 'center'
        }
    ];

    // Feature discovery hints - shown contextually
    const FEATURE_HINTS = {
        graphPanZoom: {
            id: 'graph_pan_zoom',
            title: 'Pan and Zoom',
            content: 'Drag to pan, scroll to zoom. Press "0" to reset the view.',
            trigger: '.graph-container',
            showAfterMs: 3000,
            showOnce: true
        },
        searchShortcut: {
            id: 'search_shortcut',
            title: 'Quick Search',
            content: 'Press "/" to focus the search box from anywhere.',
            trigger: '.nav-search-input',
            showOnFocus: true,
            showOnce: true
        },
        whyChainOnNode: {
            id: 'why_chain_node',
            title: 'Why is this here?',
            content: 'Press "w" to see why this package is in your closure.',
            trigger: '[data-center-node-id]',
            showAfterMs: 5000,
            showOnce: true
        },
        semanticZoom: {
            id: 'semantic_zoom',
            title: 'Semantic Zoom',
            content: 'Zoom in to see more detail. Package names appear at higher zoom levels.',
            trigger: '[data-semantic-zoom="true"]',
            showAfterMs: 4000,
            showOnce: true
        },
        compareFeature: {
            id: 'compare_feature',
            title: 'Compare Configurations',
            content: 'Import multiple hosts to compare them and find differences.',
            trigger: '[href="/compare"]',
            showAfterMs: 10000,
            showOnce: true
        },
        keyboardNavigation: {
            id: 'keyboard_nav',
            title: 'Keyboard Navigation',
            content: 'Use j/k to navigate lists, Enter to select, and o to open in a new tab.',
            trigger: '.keyboard-selected',
            showOnce: true
        }
    };

    class VizzyOnboarding {
        constructor() {
            this.currentTourStep = -1;
            this.tourActive = false;
            this.helpOverlayVisible = false;
            this.activeHint = null;
            this.hintTimeouts = {};

            this.init();
        }

        init() {
            // Check if we should show tour for first-time users
            if (this.shouldShowTour()) {
                // Delay tour start slightly for page to settle
                setTimeout(() => this.startTour(), 1500);
            }

            // Set up feature hint triggers
            this.setupFeatureHints();

            // Create help overlay (hidden by default)
            this.createHelpOverlay();

            // Listen for navigation to reset hints on page change
            document.body.addEventListener('htmx:afterSwap', () => {
                this.setupFeatureHints();
            });
        }

        // =========================================================================
        // Storage Helpers
        // =========================================================================

        getStorageItem(key, defaultValue = null) {
            try {
                const item = localStorage.getItem(key);
                return item ? JSON.parse(item) : defaultValue;
            } catch (e) {
                return defaultValue;
            }
        }

        setStorageItem(key, value) {
            try {
                localStorage.setItem(key, JSON.stringify(value));
            } catch (e) {
                console.warn('Failed to save to localStorage:', e);
            }
        }

        // =========================================================================
        // Tour Logic
        // =========================================================================

        shouldShowTour() {
            // Don't show if already completed or dismissed
            if (this.getStorageItem(STORAGE_KEYS.tourCompleted, false)) return false;
            if (this.getStorageItem(STORAGE_KEYS.tourDismissed, false)) return false;

            // Only show on pages where tour makes sense (explore, node views)
            const path = window.location.pathname;
            const tourPages = ['/explore/', '/graph/', '/dashboard/'];
            return tourPages.some(p => path.includes(p));
        }

        startTour() {
            this.tourActive = true;
            this.currentTourStep = -1;
            this.nextTourStep();
        }

        nextTourStep() {
            this.currentTourStep++;

            if (this.currentTourStep >= TOUR_STEPS.length) {
                this.completeTour();
                return;
            }

            this.showTourStep(TOUR_STEPS[this.currentTourStep]);
        }

        prevTourStep() {
            if (this.currentTourStep > 0) {
                this.currentTourStep--;
                this.showTourStep(TOUR_STEPS[this.currentTourStep]);
            }
        }

        showTourStep(step) {
            // Remove any existing tour overlay
            this.removeTourOverlay();

            // Create overlay
            const overlay = document.createElement('div');
            overlay.id = 'vizzy-tour-overlay';
            overlay.className = 'vizzy-tour-overlay';
            overlay.innerHTML = `<div class="vizzy-tour-backdrop"></div>`;

            // Find target element
            let targetEl = step.target ? document.querySelector(step.target) : null;
            if (!targetEl && step.targetFallback) {
                targetEl = document.querySelector(step.targetFallback);
            }

            // Create spotlight if target exists
            if (targetEl) {
                const rect = targetEl.getBoundingClientRect();
                const spotlight = document.createElement('div');
                spotlight.className = 'vizzy-tour-spotlight';
                spotlight.style.top = `${rect.top - 8}px`;
                spotlight.style.left = `${rect.left - 8}px`;
                spotlight.style.width = `${rect.width + 16}px`;
                spotlight.style.height = `${rect.height + 16}px`;
                overlay.appendChild(spotlight);
            }

            // Create tooltip
            const tooltip = document.createElement('div');
            tooltip.className = `vizzy-tour-tooltip vizzy-tour-tooltip-${step.position}`;
            tooltip.innerHTML = `
                <div class="vizzy-tour-tooltip-header">
                    <h3 class="vizzy-tour-tooltip-title">${step.title}</h3>
                    <button class="vizzy-tour-close" aria-label="Close tour">&times;</button>
                </div>
                <div class="vizzy-tour-tooltip-content">
                    <p>${step.content}</p>
                </div>
                <div class="vizzy-tour-tooltip-footer">
                    <div class="vizzy-tour-progress">
                        Step ${this.currentTourStep + 1} of ${TOUR_STEPS.length}
                    </div>
                    <div class="vizzy-tour-buttons">
                        ${this.currentTourStep > 0 ? '<button class="vizzy-tour-btn vizzy-tour-btn-secondary" data-tour-action="prev">Back</button>' : ''}
                        <button class="vizzy-tour-btn vizzy-tour-btn-primary" data-tour-action="next">
                            ${this.currentTourStep === TOUR_STEPS.length - 1 ? 'Finish' : 'Next'}
                        </button>
                    </div>
                </div>
            `;

            overlay.appendChild(tooltip);
            document.body.appendChild(overlay);

            // Position tooltip
            this.positionTooltip(tooltip, targetEl, step.position);

            // Add event listeners
            overlay.querySelector('.vizzy-tour-close').addEventListener('click', () => this.dismissTour());
            overlay.querySelector('[data-tour-action="next"]').addEventListener('click', () => this.nextTourStep());
            const prevBtn = overlay.querySelector('[data-tour-action="prev"]');
            if (prevBtn) {
                prevBtn.addEventListener('click', () => this.prevTourStep());
            }

            // Close on backdrop click
            overlay.querySelector('.vizzy-tour-backdrop').addEventListener('click', () => this.dismissTour());

            // Handle escape key
            const escHandler = (e) => {
                if (e.key === 'Escape') {
                    this.dismissTour();
                    document.removeEventListener('keydown', escHandler);
                }
            };
            document.addEventListener('keydown', escHandler);
        }

        positionTooltip(tooltip, targetEl, position) {
            if (!targetEl || position === 'center') {
                // Center in viewport
                tooltip.style.top = '50%';
                tooltip.style.left = '50%';
                tooltip.style.transform = 'translate(-50%, -50%)';
                return;
            }

            const rect = targetEl.getBoundingClientRect();
            const tooltipRect = tooltip.getBoundingClientRect();
            const padding = 16;

            let top, left;

            switch (position) {
                case 'top':
                    top = rect.top - tooltipRect.height - padding;
                    left = rect.left + (rect.width - tooltipRect.width) / 2;
                    break;
                case 'bottom':
                    top = rect.bottom + padding;
                    left = rect.left + (rect.width - tooltipRect.width) / 2;
                    break;
                case 'bottom-start':
                    top = rect.bottom + padding;
                    left = rect.left;
                    break;
                case 'left':
                    top = rect.top + (rect.height - tooltipRect.height) / 2;
                    left = rect.left - tooltipRect.width - padding;
                    break;
                case 'right':
                    top = rect.top + (rect.height - tooltipRect.height) / 2;
                    left = rect.right + padding;
                    break;
                default:
                    top = rect.bottom + padding;
                    left = rect.left;
            }

            // Keep tooltip in viewport
            const viewportPadding = 16;
            top = Math.max(viewportPadding, Math.min(top, window.innerHeight - tooltipRect.height - viewportPadding));
            left = Math.max(viewportPadding, Math.min(left, window.innerWidth - tooltipRect.width - viewportPadding));

            tooltip.style.top = `${top}px`;
            tooltip.style.left = `${left}px`;
        }

        removeTourOverlay() {
            const existing = document.getElementById('vizzy-tour-overlay');
            if (existing) {
                existing.remove();
            }
        }

        completeTour() {
            this.tourActive = false;
            this.removeTourOverlay();
            this.setStorageItem(STORAGE_KEYS.tourCompleted, true);
        }

        dismissTour() {
            this.tourActive = false;
            this.removeTourOverlay();
            this.setStorageItem(STORAGE_KEYS.tourDismissed, true);
        }

        restartTour() {
            this.setStorageItem(STORAGE_KEYS.tourCompleted, false);
            this.setStorageItem(STORAGE_KEYS.tourDismissed, false);
            this.startTour();
        }

        // =========================================================================
        // Feature Hints
        // =========================================================================

        setupFeatureHints() {
            // Clear existing timeouts
            Object.values(this.hintTimeouts).forEach(t => clearTimeout(t));
            this.hintTimeouts = {};

            // Don't show hints during tour
            if (this.tourActive) return;

            // Check if tips are enabled (default true)
            if (!this.getStorageItem(STORAGE_KEYS.tipsEnabled, true)) return;

            const dismissedTips = this.getStorageItem(STORAGE_KEYS.dismissedTips, []);

            for (const [key, hint] of Object.entries(FEATURE_HINTS)) {
                // Skip if already dismissed
                if (hint.showOnce && dismissedTips.includes(hint.id)) continue;

                const target = document.querySelector(hint.trigger);
                if (!target) continue;

                if (hint.showAfterMs) {
                    this.hintTimeouts[key] = setTimeout(() => {
                        this.showFeatureHint(hint, target);
                    }, hint.showAfterMs);
                }

                if (hint.showOnFocus) {
                    target.addEventListener('focus', () => {
                        if (!dismissedTips.includes(hint.id)) {
                            setTimeout(() => this.showFeatureHint(hint, target), 500);
                        }
                    }, { once: true });
                }
            }
        }

        showFeatureHint(hint, targetEl) {
            // Don't show during tour
            if (this.tourActive) return;

            // Don't show if another hint is active
            if (this.activeHint) return;

            // Don't show if help overlay is visible
            if (this.helpOverlayVisible) return;

            this.activeHint = hint.id;

            const hintEl = document.createElement('div');
            hintEl.id = 'vizzy-feature-hint';
            hintEl.className = 'vizzy-feature-hint';
            hintEl.innerHTML = `
                <div class="vizzy-hint-content">
                    <div class="vizzy-hint-icon">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <circle cx="12" cy="12" r="10"/>
                            <path d="M12 16v-4"/>
                            <path d="M12 8h.01"/>
                        </svg>
                    </div>
                    <div class="vizzy-hint-text">
                        <strong>${hint.title}:</strong> ${hint.content}
                    </div>
                    <button class="vizzy-hint-dismiss" aria-label="Dismiss tip">&times;</button>
                </div>
            `;

            document.body.appendChild(hintEl);

            // Position hint near target
            this.positionHint(hintEl, targetEl);

            // Add dismiss handler
            hintEl.querySelector('.vizzy-hint-dismiss').addEventListener('click', () => {
                this.dismissFeatureHint(hint.id);
            });

            // Auto-dismiss after 8 seconds
            setTimeout(() => {
                if (this.activeHint === hint.id) {
                    this.hideFeatureHint();
                }
            }, 8000);
        }

        positionHint(hintEl, targetEl) {
            if (!targetEl) {
                // Position at bottom right
                hintEl.style.bottom = '1rem';
                hintEl.style.right = '1rem';
                return;
            }

            const rect = targetEl.getBoundingClientRect();
            const hintRect = hintEl.getBoundingClientRect();

            // Try to position below target
            let top = rect.bottom + 12;
            let left = rect.left + (rect.width - hintRect.width) / 2;

            // Keep in viewport
            left = Math.max(16, Math.min(left, window.innerWidth - hintRect.width - 16));

            // If would go off bottom, position at bottom of screen
            if (top + hintRect.height > window.innerHeight - 16) {
                hintEl.style.bottom = '1rem';
                hintEl.style.top = 'auto';
            } else {
                hintEl.style.top = `${top}px`;
            }
            hintEl.style.left = `${left}px`;
        }

        hideFeatureHint() {
            const hint = document.getElementById('vizzy-feature-hint');
            if (hint) {
                hint.classList.add('vizzy-hint-fade-out');
                setTimeout(() => hint.remove(), 200);
            }
            this.activeHint = null;
        }

        dismissFeatureHint(hintId) {
            this.hideFeatureHint();

            // Mark as dismissed
            const dismissed = this.getStorageItem(STORAGE_KEYS.dismissedTips, []);
            if (!dismissed.includes(hintId)) {
                dismissed.push(hintId);
                this.setStorageItem(STORAGE_KEYS.dismissedTips, dismissed);
            }
        }

        // =========================================================================
        // Help Overlay
        // =========================================================================

        createHelpOverlay() {
            const overlay = document.createElement('div');
            overlay.id = 'vizzy-help-overlay';
            overlay.className = 'vizzy-help-overlay hidden';
            overlay.setAttribute('role', 'dialog');
            overlay.setAttribute('aria-modal', 'true');
            overlay.setAttribute('aria-labelledby', 'vizzy-help-title');

            overlay.innerHTML = `
                <div class="vizzy-help-backdrop"></div>
                <div class="vizzy-help-panel">
                    <div class="vizzy-help-header">
                        <h2 id="vizzy-help-title">Help & Onboarding</h2>
                        <button class="vizzy-help-close" aria-label="Close">&times;</button>
                    </div>
                    <div class="vizzy-help-body">
                        <div class="vizzy-help-section">
                            <h3>Quick Start Tour</h3>
                            <p>New to Vizzy? Take a quick tour to learn the basics.</p>
                            <button class="vizzy-help-action-btn" data-action="restart-tour">
                                <svg class="vizzy-help-action-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                    <path d="M1 4v6h6"/>
                                    <path d="M3.51 15a9 9 0 102.13-9.36L1 10"/>
                                </svg>
                                Start Tour
                            </button>
                        </div>

                        <div class="vizzy-help-section">
                            <h3>Feature Guides</h3>
                            <div class="vizzy-help-features">
                                <div class="vizzy-help-feature" data-feature="graph">
                                    <div class="vizzy-help-feature-icon">
                                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                            <circle cx="12" cy="12" r="3"/>
                                            <circle cx="19" cy="5" r="2"/>
                                            <circle cx="5" cy="19" r="2"/>
                                            <circle cx="5" cy="5" r="2"/>
                                            <line x1="12" y1="9" x2="12" y2="3"/>
                                            <line x1="9" y1="12" x2="3" y2="12"/>
                                            <line x1="14" y1="14" x2="19" y2="19"/>
                                        </svg>
                                    </div>
                                    <div class="vizzy-help-feature-text">
                                        <strong>Graph Exploration</strong>
                                        <span>Pan, zoom, and navigate the dependency graph</span>
                                    </div>
                                </div>
                                <div class="vizzy-help-feature" data-feature="search">
                                    <div class="vizzy-help-feature-icon">
                                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                            <circle cx="11" cy="11" r="8"/>
                                            <line x1="21" y1="21" x2="16.65" y2="16.65"/>
                                        </svg>
                                    </div>
                                    <div class="vizzy-help-feature-text">
                                        <strong>Search</strong>
                                        <span>Find packages quickly with fuzzy search</span>
                                    </div>
                                </div>
                                <div class="vizzy-help-feature" data-feature="analysis">
                                    <div class="vizzy-help-feature-icon">
                                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                            <path d="M21 21H4.6c-.6 0-1.1-.5-1.1-1.1V3"/>
                                            <path d="M7 14l4-4 4 4 6-6"/>
                                        </svg>
                                    </div>
                                    <div class="vizzy-help-feature-text">
                                        <strong>Analysis Tools</strong>
                                        <span>Find duplicates, loops, and redundant links</span>
                                    </div>
                                </div>
                                <div class="vizzy-help-feature" data-feature="whychain">
                                    <div class="vizzy-help-feature-icon">
                                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                            <circle cx="12" cy="12" r="10"/>
                                            <path d="M9.09 9a3 3 0 015.83 1c0 2-3 3-3 3"/>
                                            <line x1="12" y1="17" x2="12.01" y2="17"/>
                                        </svg>
                                    </div>
                                    <div class="vizzy-help-feature-text">
                                        <strong>Why Chain</strong>
                                        <span>Understand why packages are in your closure</span>
                                    </div>
                                </div>
                                <div class="vizzy-help-feature" data-feature="compare">
                                    <div class="vizzy-help-feature-icon">
                                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                            <line x1="18" y1="20" x2="18" y2="10"/>
                                            <line x1="12" y1="20" x2="12" y2="4"/>
                                            <line x1="6" y1="20" x2="6" y2="14"/>
                                        </svg>
                                    </div>
                                    <div class="vizzy-help-feature-text">
                                        <strong>Compare</strong>
                                        <span>Diff two configurations side-by-side</span>
                                    </div>
                                </div>
                            </div>
                        </div>

                        <div class="vizzy-help-section">
                            <h3>Keyboard Shortcuts</h3>
                            <p>Press <kbd>?</kbd> to see all keyboard shortcuts, or click below.</p>
                            <button class="vizzy-help-action-btn vizzy-help-action-secondary" data-action="show-shortcuts">
                                <svg class="vizzy-help-action-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                    <rect x="2" y="4" width="20" height="16" rx="2"/>
                                    <path d="M6 8h.01"/>
                                    <path d="M10 8h.01"/>
                                    <path d="M14 8h.01"/>
                                    <path d="M18 8h.01"/>
                                    <path d="M6 12h.01"/>
                                    <path d="M18 12h.01"/>
                                    <path d="M8 16h8"/>
                                </svg>
                                View Keyboard Shortcuts
                            </button>
                        </div>

                        <div class="vizzy-help-section">
                            <h3>Tips & Hints</h3>
                            <div class="vizzy-help-toggle">
                                <label class="vizzy-help-toggle-label">
                                    <input type="checkbox" id="vizzy-tips-toggle" checked>
                                    <span>Show contextual tips and hints</span>
                                </label>
                            </div>
                            <button class="vizzy-help-action-btn vizzy-help-action-tertiary" data-action="reset-tips">
                                Reset dismissed tips
                            </button>
                        </div>
                    </div>
                </div>
            `;

            document.body.appendChild(overlay);

            // Set up event listeners
            overlay.querySelector('.vizzy-help-close').addEventListener('click', () => this.hideHelpOverlay());
            overlay.querySelector('.vizzy-help-backdrop').addEventListener('click', () => this.hideHelpOverlay());

            overlay.querySelector('[data-action="restart-tour"]').addEventListener('click', () => {
                this.hideHelpOverlay();
                setTimeout(() => this.restartTour(), 300);
            });

            overlay.querySelector('[data-action="show-shortcuts"]').addEventListener('click', () => {
                this.hideHelpOverlay();
                setTimeout(() => {
                    if (window.vizzyKeyboardNav) {
                        window.vizzyKeyboardNav.toggleHelpModal();
                    }
                }, 300);
            });

            overlay.querySelector('[data-action="reset-tips"]').addEventListener('click', () => {
                this.setStorageItem(STORAGE_KEYS.dismissedTips, []);
                alert('Tips have been reset. You will see contextual hints again.');
            });

            // Tips toggle
            const tipsToggle = overlay.querySelector('#vizzy-tips-toggle');
            tipsToggle.checked = this.getStorageItem(STORAGE_KEYS.tipsEnabled, true);
            tipsToggle.addEventListener('change', (e) => {
                this.setStorageItem(STORAGE_KEYS.tipsEnabled, e.target.checked);
            });

            // Feature card clicks show detailed help
            overlay.querySelectorAll('.vizzy-help-feature').forEach(card => {
                card.addEventListener('click', () => {
                    const feature = card.dataset.feature;
                    this.showFeatureHelp(feature);
                });
            });
        }

        showHelpOverlay() {
            const overlay = document.getElementById('vizzy-help-overlay');
            if (overlay) {
                overlay.classList.remove('hidden');
                this.helpOverlayVisible = true;

                // Focus trap
                overlay.querySelector('.vizzy-help-close').focus();
            }
        }

        hideHelpOverlay() {
            const overlay = document.getElementById('vizzy-help-overlay');
            if (overlay) {
                overlay.classList.add('hidden');
                this.helpOverlayVisible = false;
            }
        }

        toggleHelpOverlay() {
            if (this.helpOverlayVisible) {
                this.hideHelpOverlay();
            } else {
                this.showHelpOverlay();
            }
        }

        showFeatureHelp(feature) {
            const helpContent = {
                graph: {
                    title: 'Graph Exploration',
                    content: `
                        <h4>Navigation</h4>
                        <ul>
                            <li><strong>Pan:</strong> Click and drag anywhere on the graph</li>
                            <li><strong>Zoom:</strong> Scroll up/down or use +/- keys</li>
                            <li><strong>Reset:</strong> Press "0" or double-click</li>
                        </ul>
                        <h4>Semantic Zoom</h4>
                        <p>As you zoom in, more details appear:</p>
                        <ul>
                            <li>Zoomed out: Package type clusters</li>
                            <li>Zoomed in: Individual package names</li>
                            <li>Very close: Full derivation paths</li>
                        </ul>
                        <h4>Interaction</h4>
                        <ul>
                            <li>Click a node to view its details</li>
                            <li>Hover to highlight connections</li>
                        </ul>
                    `
                },
                search: {
                    title: 'Search',
                    content: `
                        <h4>Quick Access</h4>
                        <p>Press <kbd>/</kbd> from anywhere to focus the search box.</p>
                        <h4>Search Tips</h4>
                        <ul>
                            <li>Search by package name (e.g., "python")</li>
                            <li>Fuzzy matching finds partial matches</li>
                            <li>Results appear as you type</li>
                        </ul>
                        <h4>Navigation</h4>
                        <ul>
                            <li>Use <kbd>j</kbd>/<kbd>k</kbd> to move through results</li>
                            <li>Press <kbd>Enter</kbd> to open selected result</li>
                            <li>Press <kbd>o</kbd> to open in new tab</li>
                        </ul>
                    `
                },
                analysis: {
                    title: 'Analysis Tools',
                    content: `
                        <h4>Available Tools</h4>
                        <ul>
                            <li><strong>Duplicates (<kbd>d</kbd>):</strong> Find packages with multiple versions</li>
                            <li><strong>Path Finder (<kbd>p</kbd>):</strong> Find dependency paths between packages</li>
                            <li><strong>Loops (<kbd>l</kbd>):</strong> Detect circular dependencies</li>
                            <li><strong>Redundant (<kbd>r</kbd>):</strong> Find unnecessary transitive links</li>
                        </ul>
                        <h4>Using Results</h4>
                        <p>Click any result to navigate to that package's detail view.</p>
                    `
                },
                whychain: {
                    title: 'Why Chain',
                    content: `
                        <h4>Understanding Attribution</h4>
                        <p>The Why Chain answers: "Why is this package in my closure?"</p>
                        <h4>Access</h4>
                        <ul>
                            <li>From any node view, press <kbd>w</kbd></li>
                            <li>Or click "Why Chain" in the Analysis section</li>
                        </ul>
                        <h4>Reading the Chain</h4>
                        <ul>
                            <li><strong>Top-level:</strong> Packages you explicitly requested</li>
                            <li><strong>Intermediate:</strong> Packages in the dependency path</li>
                            <li><strong>Target:</strong> The package you're investigating</li>
                        </ul>
                    `
                },
                compare: {
                    title: 'Configuration Comparison',
                    content: `
                        <h4>Getting Started</h4>
                        <p>Import at least two configurations to enable comparison.</p>
                        <h4>Comparison Views</h4>
                        <ul>
                            <li><strong>Full Diff:</strong> All packages added/removed</li>
                            <li><strong>By Type:</strong> Filter by package category</li>
                            <li><strong>Version Diff:</strong> Same package, different versions</li>
                        </ul>
                        <h4>Baselines</h4>
                        <p>Save a configuration as a baseline to track changes over time.</p>
                    `
                }
            };

            const info = helpContent[feature];
            if (!info) return;

            // Update the help panel to show detailed feature help
            const panel = document.querySelector('.vizzy-help-panel');
            if (!panel) return;

            const body = panel.querySelector('.vizzy-help-body');
            const originalContent = body.innerHTML;

            body.innerHTML = `
                <div class="vizzy-help-feature-detail">
                    <button class="vizzy-help-back" aria-label="Back to help menu">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M19 12H5"/>
                            <path d="M12 19l-7-7 7-7"/>
                        </svg>
                        Back
                    </button>
                    <h3>${info.title}</h3>
                    <div class="vizzy-help-feature-content">
                        ${info.content}
                    </div>
                </div>
            `;

            body.querySelector('.vizzy-help-back').addEventListener('click', () => {
                body.innerHTML = originalContent;
                // Re-attach feature card listeners
                body.querySelectorAll('.vizzy-help-feature').forEach(card => {
                    card.addEventListener('click', () => {
                        this.showFeatureHelp(card.dataset.feature);
                    });
                });
                // Re-attach other listeners
                body.querySelector('[data-action="restart-tour"]')?.addEventListener('click', () => {
                    this.hideHelpOverlay();
                    setTimeout(() => this.restartTour(), 300);
                });
                body.querySelector('[data-action="show-shortcuts"]')?.addEventListener('click', () => {
                    this.hideHelpOverlay();
                    setTimeout(() => {
                        if (window.vizzyKeyboardNav) {
                            window.vizzyKeyboardNav.toggleHelpModal();
                        }
                    }, 300);
                });
                body.querySelector('[data-action="reset-tips"]')?.addEventListener('click', () => {
                    this.setStorageItem(STORAGE_KEYS.dismissedTips, []);
                    alert('Tips have been reset. You will see contextual hints again.');
                });
                const tipsToggle = body.querySelector('#vizzy-tips-toggle');
                if (tipsToggle) {
                    tipsToggle.checked = this.getStorageItem(STORAGE_KEYS.tipsEnabled, true);
                    tipsToggle.addEventListener('change', (e) => {
                        this.setStorageItem(STORAGE_KEYS.tipsEnabled, e.target.checked);
                    });
                }
            });
        }
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            window.vizzyOnboarding = new VizzyOnboarding();
        });
    } else {
        window.vizzyOnboarding = new VizzyOnboarding();
    }
})();
