// Graph Navigation - Pan/Zoom for Graphviz SVG renderings

class GraphNavigator {
    constructor(container) {
        this.container = container;
        this.svg = container.querySelector('svg');
        if (!this.svg) return;

        this.scale = 1;
        this.translateX = 0;
        this.translateY = 0;
        this.isPanning = false;
        this.lastPanX = 0;
        this.lastPanY = 0;

        // Touch support state
        this.lastTouchDistance = 0;
        this.lastTouchCenter = { x: 0, y: 0 };

        // Animation frame throttling for smooth performance
        this.pendingUpdate = false;
        this.rafId = null;

        this.init();
    }

    init() {
        // Wrap SVG content in a group for transformations
        // Check if already wrapped (for HTMX swaps)
        if (!this.svg.querySelector('.pan-zoom-group')) {
            const content = this.svg.innerHTML;
            this.svg.innerHTML = `<g class="pan-zoom-group">${content}</g>`;
        }
        this.group = this.svg.querySelector('.pan-zoom-group');

        // Make SVG fill container and disable default overflow scroll
        this.svg.style.width = '100%';
        this.svg.style.height = '100%';
        this.svg.style.overflow = 'visible';
        this.container.style.overflow = 'hidden';

        // Set up event listeners
        this.container.addEventListener('wheel', this.handleZoom.bind(this), { passive: false });
        this.container.addEventListener('mousedown', this.startPan.bind(this));
        this.container.addEventListener('mousemove', this.doPan.bind(this));
        this.container.addEventListener('mouseup', this.endPan.bind(this));
        this.container.addEventListener('mouseleave', this.endPan.bind(this));

        // Touch support
        this.container.addEventListener('touchstart', this.handleTouchStart.bind(this), { passive: false });
        this.container.addEventListener('touchmove', this.handleTouchMove.bind(this), { passive: false });
        this.container.addEventListener('touchend', this.endPan.bind(this));

        // Add controls
        this.addControls();

        // Initial fit to container
        requestAnimationFrame(() => this.fitToContainer());
    }

    handleZoom(e) {
        e.preventDefault();

        const rect = this.container.getBoundingClientRect();

        // Mouse position relative to container (in screen pixels)
        const mouseX = e.clientX - rect.left;
        const mouseY = e.clientY - rect.top;

        // Convert to SVG viewBox coordinates (includes viewBox origin offset)
        const viewBox = this.svg.viewBox.baseVal;
        const vbX = viewBox.x || 0;
        const vbY = viewBox.y || 0;
        const svgX = viewBox.width > 0 ? mouseX * (viewBox.width / rect.width) + vbX : mouseX;
        const svgY = viewBox.height > 0 ? mouseY * (viewBox.height / rect.height) + vbY : mouseY;

        const delta = e.deltaY > 0 ? 0.9 : 1.1;
        const newScale = Math.max(0.1, Math.min(5, this.scale * delta));

        // With transform="translate(tx,ty) scale(s)": output = s * P + translate
        // For point P under mouse at viewBox position M: M = s * P + translate
        // So P = (M - translate) / s
        // After zoom: M = newS * P + newTranslate
        // newTranslate = M - newS * (M - translate) / s
        // delta = newTranslate - translate = (M - translate) * (s - newS) / s
        this.translateX += (svgX - this.translateX) * (this.scale - newScale) / this.scale;
        this.translateY += (svgY - this.translateY) * (this.scale - newScale) / this.scale;
        this.scale = newScale;

        this.scheduleUpdate();
    }

    startPan(e) {
        // Don't pan when clicking links
        if (e.target.closest('a')) return;

        e.preventDefault(); // Prevent text selection
        this.isPanning = true;
        this.lastPanX = e.clientX;
        this.lastPanY = e.clientY;
        this.container.style.cursor = 'grabbing';
    }

    doPan(e) {
        if (!this.isPanning) return;

        // Convert screen pixel delta to viewBox coordinates
        // Use uniform scale for consistent panning in all directions
        const rect = this.container.getBoundingClientRect();
        const viewBox = this.svg.viewBox.baseVal;
        const scale = viewBox.width > 0 && viewBox.height > 0
            ? Math.max(viewBox.width / rect.width, viewBox.height / rect.height)
            : 1;

        const dx = (e.clientX - this.lastPanX) * scale;
        const dy = (e.clientY - this.lastPanY) * scale;

        this.translateX += dx;
        this.translateY += dy;
        this.lastPanX = e.clientX;
        this.lastPanY = e.clientY;

        this.scheduleUpdate();
    }

    scheduleUpdate() {
        if (this.pendingUpdate) return;
        this.pendingUpdate = true;
        this.rafId = requestAnimationFrame(() => {
            this.applyTransform();
            this.pendingUpdate = false;
        });
    }

    endPan() {
        this.isPanning = false;
        this.container.style.cursor = 'grab';
    }

    handleTouchStart(e) {
        if (e.touches.length === 1) {
            // Single touch - pan
            const touch = e.touches[0];
            this.isPanning = true;
            this.lastPanX = touch.clientX;
            this.lastPanY = touch.clientY;
        } else if (e.touches.length === 2) {
            // Two fingers - pinch zoom
            e.preventDefault();
            this.isPanning = false;
            this.lastTouchDistance = this.getTouchDistance(e.touches);
            this.lastTouchCenter = this.getTouchCenter(e.touches);
        }
    }

    handleTouchMove(e) {
        if (e.touches.length === 1 && this.isPanning) {
            // Single touch - pan
            const touch = e.touches[0];
            // Convert screen pixel delta to viewBox coordinates
            // Use uniform scale for consistent panning in all directions
            const rect = this.container.getBoundingClientRect();
            const viewBox = this.svg.viewBox.baseVal;
            const scale = viewBox.width > 0 && viewBox.height > 0
                ? Math.max(viewBox.width / rect.width, viewBox.height / rect.height)
                : 1;

            const dx = (touch.clientX - this.lastPanX) * scale;
            const dy = (touch.clientY - this.lastPanY) * scale;

            this.translateX += dx;
            this.translateY += dy;
            this.lastPanX = touch.clientX;
            this.lastPanY = touch.clientY;

            this.scheduleUpdate();
        } else if (e.touches.length === 2) {
            // Two fingers - pinch zoom
            e.preventDefault();
            const distance = this.getTouchDistance(e.touches);
            const center = this.getTouchCenter(e.touches);
            const rect = this.container.getBoundingClientRect();

            // Convert pinch center to SVG viewBox coordinates
            const mouseX = center.x - rect.left;
            const mouseY = center.y - rect.top;
            const viewBox = this.svg.viewBox.baseVal;
            const vbX = viewBox.x || 0;
            const vbY = viewBox.y || 0;
            const svgX = viewBox.width > 0 ? mouseX * (viewBox.width / rect.width) + vbX : mouseX;
            const svgY = viewBox.height > 0 ? mouseY * (viewBox.height / rect.height) + vbY : mouseY;

            // Calculate scale change
            const scaleChange = distance / this.lastTouchDistance;
            const newScale = Math.max(0.1, Math.min(5, this.scale * scaleChange));

            // Same formula as handleZoom: delta = (M - translate) * (s - newS) / s
            this.translateX += (svgX - this.translateX) * (this.scale - newScale) / this.scale;
            this.translateY += (svgY - this.translateY) * (this.scale - newScale) / this.scale;
            this.scale = newScale;

            // Update for next move
            this.lastTouchDistance = distance;
            this.lastTouchCenter = center;

            this.scheduleUpdate();
        }
    }

    getTouchDistance(touches) {
        const dx = touches[0].clientX - touches[1].clientX;
        const dy = touches[0].clientY - touches[1].clientY;
        return Math.sqrt(dx * dx + dy * dy);
    }

    getTouchCenter(touches) {
        return {
            x: (touches[0].clientX + touches[1].clientX) / 2,
            y: (touches[0].clientY + touches[1].clientY) / 2
        };
    }

    applyTransform() {
        // Order: translate first, then scale (matching semantic-zoom.js)
        this.group.setAttribute('transform',
            `translate(${this.translateX}, ${this.translateY}) scale(${this.scale})`
        );
    }

    reset() {
        this.scale = 1;
        this.translateX = 0;
        this.translateY = 0;
        this.applyTransform();
        this.fitToContainer();
    }

    fitToContainer(retryCount = 0) {
        const containerRect = this.container.getBoundingClientRect();

        // Retry if container not ready
        if ((containerRect.width === 0 || containerRect.height === 0) && retryCount < 10) {
            setTimeout(() => this.fitToContainer(retryCount + 1), 50);
            return;
        }

        // Get actual rendered bounds using getBBox on the group
        let bbox;
        try {
            bbox = this.group.getBBox();
        } catch (err) {
            if (retryCount < 10) {
                setTimeout(() => this.fitToContainer(retryCount + 1), 50);
            }
            return;
        }

        if (bbox.width === 0 || bbox.height === 0) {
            if (retryCount < 10) {
                setTimeout(() => this.fitToContainer(retryCount + 1), 50);
            }
            return;
        }

        // Get viewBox to work in SVG coordinates
        const viewBox = this.svg.viewBox.baseVal;
        const vbWidth = viewBox.width > 0 ? viewBox.width : containerRect.width;
        const vbHeight = viewBox.height > 0 ? viewBox.height : containerRect.height;
        const vbX = viewBox.x || 0;
        const vbY = viewBox.y || 0;

        // Calculate scale to fit bbox within viewBox (with padding in SVG units)
        const paddingRatio = 0.05; // 5% padding
        const availableWidth = vbWidth * (1 - paddingRatio * 2);
        const availableHeight = vbHeight * (1 - paddingRatio * 2);

        const scaleX = availableWidth / bbox.width;
        const scaleY = availableHeight / bbox.height;
        this.scale = Math.min(scaleX, scaleY, 1.5);

        // Center of viewBox (in SVG coordinates)
        const viewBoxCenterX = vbX + vbWidth / 2;
        const viewBoxCenterY = vbY + vbHeight / 2;

        // Center of content bbox
        const bboxCenterX = bbox.x + bbox.width / 2;
        const bboxCenterY = bbox.y + bbox.height / 2;

        // With transform="translate(tx,ty) scale(s)": screenPos = s * content + translate
        // We want: s * bboxCenter + translate = viewBoxCenter
        // translate = viewBoxCenter - s * bboxCenter
        this.translateX = viewBoxCenterX - this.scale * bboxCenterX;
        this.translateY = viewBoxCenterY - this.scale * bboxCenterY;

        this.applyTransform();
    }

    addControls() {
        // Remove existing controls if any (for HTMX swaps)
        const existing = this.container.querySelector('.graph-controls');
        if (existing) existing.remove();

        const controls = document.createElement('div');
        controls.className = 'graph-controls';
        controls.setAttribute('role', 'group');
        controls.setAttribute('aria-label', 'Graph zoom controls');
        controls.innerHTML = `
            <button class="zoom-in" title="Zoom In (scroll up or press +)" aria-label="Zoom in">+</button>
            <button class="zoom-out" title="Zoom Out (scroll down or press -)" aria-label="Zoom out">-</button>
            <button class="zoom-reset" title="Reset View (press 0)" aria-label="Reset view">&#x21BA;</button>
        `;

        controls.querySelector('.zoom-in').addEventListener('click', () => {
            this.scale = Math.min(5, this.scale * 1.2);
            this.applyTransform();
        });

        controls.querySelector('.zoom-out').addEventListener('click', () => {
            this.scale = Math.max(0.1, this.scale / 1.2);
            this.applyTransform();
        });

        controls.querySelector('.zoom-reset').addEventListener('click', () => {
            this.reset();
        });

        this.container.style.position = 'relative';
        this.container.appendChild(controls);
    }
}

// Initialize on DOM ready
function initGraphNavigators() {
    document.querySelectorAll('.graph-container').forEach(container => {
        // Skip if already initialized
        if (container._graphNavigator) return;
        container._graphNavigator = new GraphNavigator(container);
    });
}

document.addEventListener('DOMContentLoaded', initGraphNavigators);

// Re-initialize after HTMX swaps (for dynamic content)
document.body.addEventListener('htmx:afterSwap', (e) => {
    // Small delay to ensure SVG is rendered
    requestAnimationFrame(() => {
        const containers = e.detail.target.querySelectorAll('.graph-container');
        containers.forEach(container => {
            container._graphNavigator = new GraphNavigator(container);
        });
    });
});

// Also handle HTMX out-of-band swaps
document.body.addEventListener('htmx:oobAfterSwap', (e) => {
    requestAnimationFrame(() => {
        const containers = e.detail.target.querySelectorAll('.graph-container');
        containers.forEach(container => {
            container._graphNavigator = new GraphNavigator(container);
        });
    });
});
