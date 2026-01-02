// Vizzy Accessibility Utilities
// Phase 8H-004: Accessibility audit and fixes

(function() {
    'use strict';

    /**
     * Vizzy Accessibility Manager
     * Handles screen reader announcements, focus management, and other a11y features
     */
    class VizzyA11y {
        constructor() {
            this.announcer = null;
            this.alertAnnouncer = null;
            this.announcementQueue = [];
            this.isProcessing = false;

            this.init();
        }

        init() {
            // Wait for DOM to be ready
            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', () => this.setup());
            } else {
                this.setup();
            }
        }

        setup() {
            // Get or create announcer elements
            this.announcer = document.getElementById('a11y-announcer');
            this.alertAnnouncer = document.getElementById('a11y-alert');

            // Create if they don't exist
            if (!this.announcer) {
                this.announcer = this.createAnnouncer('a11y-announcer', 'polite', 'status');
                document.body.appendChild(this.announcer);
            }

            if (!this.alertAnnouncer) {
                this.alertAnnouncer = this.createAnnouncer('a11y-alert', 'assertive', 'alert');
                document.body.appendChild(this.alertAnnouncer);
            }

            // Setup HTMX integration for dynamic content announcements
            this.setupHTMXIntegration();

            // Setup focus management
            this.setupFocusManagement();

            // Monitor for reduced motion preference
            this.setupReducedMotionSupport();
        }

        /**
         * Create an announcer element for screen readers
         */
        createAnnouncer(id, politeness, role) {
            const announcer = document.createElement('div');
            announcer.id = id;
            announcer.className = 'a11y-announcer';
            announcer.setAttribute('aria-live', politeness);
            announcer.setAttribute('aria-atomic', 'true');
            announcer.setAttribute('role', role);
            return announcer;
        }

        /**
         * Announce a message to screen readers
         * @param {string} message - The message to announce
         * @param {string} priority - 'polite' or 'assertive'
         */
        announce(message, priority = 'polite') {
            if (!message) return;

            const announcer = priority === 'assertive' ? this.alertAnnouncer : this.announcer;

            // Queue the announcement
            this.announcementQueue.push({ message, announcer });

            if (!this.isProcessing) {
                this.processQueue();
            }
        }

        /**
         * Process the announcement queue with delays to ensure screen readers catch them
         */
        processQueue() {
            if (this.announcementQueue.length === 0) {
                this.isProcessing = false;
                return;
            }

            this.isProcessing = true;
            const { message, announcer } = this.announcementQueue.shift();

            // Clear and set new message
            announcer.textContent = '';

            // Small delay ensures screen readers pick up the change
            requestAnimationFrame(() => {
                setTimeout(() => {
                    announcer.textContent = message;

                    // Clear after announcement and process next
                    setTimeout(() => {
                        announcer.textContent = '';
                        this.processQueue();
                    }, 1000);
                }, 100);
            });
        }

        /**
         * Announce loading state
         */
        announceLoading(context = '') {
            const message = context ? `Loading ${context}...` : 'Loading...';
            this.announce(message, 'polite');
        }

        /**
         * Announce completion of an action
         */
        announceComplete(action) {
            this.announce(`${action} complete`, 'polite');
        }

        /**
         * Announce an error
         */
        announceError(error) {
            this.announce(`Error: ${error}`, 'assertive');
        }

        /**
         * Announce navigation to a new page/section
         */
        announceNavigation(destination) {
            this.announce(`Navigated to ${destination}`, 'polite');
        }

        /**
         * Announce search results
         */
        announceSearchResults(count) {
            const message = count === 0
                ? 'No results found'
                : count === 1
                    ? '1 result found'
                    : `${count} results found`;
            this.announce(message, 'polite');
        }

        /**
         * Setup HTMX integration for automatic announcements
         */
        setupHTMXIntegration() {
            // Announce when HTMX starts a request
            document.body.addEventListener('htmx:beforeRequest', (event) => {
                const target = event.detail.target;
                const context = target.getAttribute('aria-label') ||
                               target.getAttribute('data-loading-text') ||
                               'content';

                // Set loading state on target
                target.setAttribute('aria-busy', 'true');

                // Announce loading (with debounce to avoid spam)
                if (!this._loadingDebounce) {
                    this.announceLoading(context);
                    this._loadingDebounce = setTimeout(() => {
                        this._loadingDebounce = null;
                    }, 1000);
                }
            });

            // Announce when HTMX completes
            document.body.addEventListener('htmx:afterSwap', (event) => {
                const target = event.detail.target;

                // Clear loading state
                target.removeAttribute('aria-busy');

                // Check for search results
                if (target.id === 'search-results') {
                    const resultCount = target.querySelectorAll('a, li').length;
                    this.announceSearchResults(resultCount);
                }

                // Announce content update for specific areas
                const announcementText = target.getAttribute('data-announce-on-update');
                if (announcementText) {
                    this.announce(announcementText, 'polite');
                }
            });

            // Announce errors
            document.body.addEventListener('htmx:responseError', (event) => {
                this.announceError('Failed to load content');
            });
        }

        /**
         * Setup focus management for better keyboard navigation
         */
        setupFocusManagement() {
            // Track focus for skip link functionality
            document.addEventListener('keydown', (event) => {
                // Tab key tracking for focus management
                if (event.key === 'Tab') {
                    document.body.classList.add('keyboard-navigation');
                }
            });

            document.addEventListener('mousedown', () => {
                document.body.classList.remove('keyboard-navigation');
            });

            // Focus trap for modals
            document.addEventListener('keydown', (event) => {
                const modal = document.querySelector('[aria-modal="true"]:not(.hidden)');
                if (!modal) return;

                if (event.key === 'Tab') {
                    const focusableElements = modal.querySelectorAll(
                        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
                    );

                    if (focusableElements.length === 0) return;

                    const firstElement = focusableElements[0];
                    const lastElement = focusableElements[focusableElements.length - 1];

                    if (event.shiftKey && document.activeElement === firstElement) {
                        event.preventDefault();
                        lastElement.focus();
                    } else if (!event.shiftKey && document.activeElement === lastElement) {
                        event.preventDefault();
                        firstElement.focus();
                    }
                }

                // Escape to close modal
                if (event.key === 'Escape') {
                    const closeButton = modal.querySelector('[data-close], .keyboard-help-close');
                    if (closeButton) {
                        closeButton.click();
                    }
                }
            });
        }

        /**
         * Setup reduced motion support
         */
        setupReducedMotionSupport() {
            const mediaQuery = window.matchMedia('(prefers-reduced-motion: reduce)');

            const handleReducedMotion = (e) => {
                if (e.matches) {
                    document.documentElement.classList.add('reduce-motion');
                } else {
                    document.documentElement.classList.remove('reduce-motion');
                }
            };

            // Initial check
            handleReducedMotion(mediaQuery);

            // Listen for changes
            if (mediaQuery.addEventListener) {
                mediaQuery.addEventListener('change', handleReducedMotion);
            } else {
                // Fallback for older browsers
                mediaQuery.addListener(handleReducedMotion);
            }
        }

        /**
         * Move focus to an element (used after page updates)
         */
        focusElement(selector) {
            const element = typeof selector === 'string'
                ? document.querySelector(selector)
                : selector;

            if (element) {
                // Make sure it's focusable
                if (!element.hasAttribute('tabindex')) {
                    element.setAttribute('tabindex', '-1');
                }
                element.focus();
            }
        }

        /**
         * Get the current focus context for announcements
         */
        getFocusContext() {
            const active = document.activeElement;
            if (!active || active === document.body) return null;

            return active.getAttribute('aria-label') ||
                   active.textContent?.trim().substring(0, 50) ||
                   active.tagName.toLowerCase();
        }
    }

    // Create global instance
    window.vizzyA11y = new VizzyA11y();

    // Convenience functions for easy access
    window.announce = (message, priority) => window.vizzyA11y.announce(message, priority);
    window.announceLoading = (context) => window.vizzyA11y.announceLoading(context);
    window.announceError = (error) => window.vizzyA11y.announceError(error);
    window.announceComplete = (action) => window.vizzyA11y.announceComplete(action);

})();
