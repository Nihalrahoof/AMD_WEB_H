// ============================================
// AUTOMIND DYNAMICS - Premium JavaScript v2.4.3
// MODIFIED: Eager load 3D models
// MODIFIED: Two-way scroll animation
// ============================================

// Assign Three.js to a shorter variable
const THREE = window.THREE;

// Global object to store scenes
const scenes = {};

/**
 * Initializes the full-page Premium Particle Network Background (Canvas 2D)
 * Replaces Three.js with a cleaner, highly-performant 2D implementation
 */
function initBackground3D() {
    const canvas = document.getElementById("bg-canvas");
    if (!canvas) return;

    // Switch to 2D context
    const ctx = canvas.getContext('2d');

    // Configuration
    let width, height;
    let particles = [];

    // Tuning for "Premium" feel based on user request
    const particleCountInitial = 80; // Dense enough but not cluttered
    const connectionDistance = 140;   // Distance to draw lines
    const mouseDistance = 180;        // Interaction radius

    // Resize Handler
    function resize() {
        width = window.innerWidth;
        height = window.innerHeight;
        canvas.width = width;
        canvas.height = height;

        // Adjust particle count for screen size
        const area = width * height;
        const targetCount = Math.floor(area / 15000); // 1 particle per 15000px
        const count = Math.min(Math.max(targetCount, 40), 120); // Clamp between 40 and 120

        initParticles(count);
    }

    // Particle Class
    class Particle {
        constructor() {
            this.x = Math.random() * width;
            this.y = Math.random() * height;
            // Slow, elegant floating movement
            this.vx = (Math.random() - 0.5) * 0.4;
            this.vy = (Math.random() - 0.5) * 0.4;
            this.size = Math.random() * 1.5 + 1; // Slightly varied sizes
            this.baseColor = 'rgba(255, 255, 255, 0.6)'; // White
        }

        update() {
            this.x += this.vx;
            this.y += this.vy;

            // Bounce off edges with damping
            if (this.x < 0 || this.x > width) this.vx *= -1;
            if (this.y < 0 || this.y > height) this.vy *= -1;
        }

        draw() {
            ctx.fillStyle = this.baseColor;
            ctx.beginPath();
            ctx.arc(this.x, this.y, this.size, 0, Math.PI * 2);
            ctx.fill();
        }
    }

    function initParticles(count) {
        particles = [];
        for (let i = 0; i < count; i++) {
            particles.push(new Particle());
        }
    }

    // Mouse Interaction
    let mouse = { x: null, y: null };

    // Use passive listener for performance
    window.addEventListener('mousemove', (e) => {
        mouse.x = e.clientX;
        mouse.y = e.clientY;
        // Note: For fixed background canvas, clientY is correct.
    }, { passive: true });

    window.addEventListener('mouseout', () => {
        mouse.x = null;
        mouse.y = null;
    });

    // Animation Loop
    function animate() {
        ctx.clearRect(0, 0, width, height);

        // Update & Draw Particles
        particles.forEach(p => {
            p.update();
            p.draw();
        });

        // Draw Connections
        // Optimization: nested loop j=i+1 avoids duplicate checks
        for (let i = 0; i < particles.length; i++) {
            const p1 = particles[i];

            // 1. Check Mouse Interaction first (High priority visual)
            if (mouse.x != null) {
                const dx = p1.x - mouse.x;
                const dy = p1.y - mouse.y;
                const distV = Math.sqrt(dx * dx + dy * dy);

                if (distV < mouseDistance) {
                    // Interaction Line - White
                    const opacity = 1 - (distV / mouseDistance);
                    ctx.strokeStyle = `rgba(255, 255, 255, ${opacity * 0.5})`;
                    ctx.lineWidth = 1;
                    ctx.beginPath();
                    ctx.moveTo(p1.x, p1.y);
                    ctx.lineTo(mouse.x, mouse.y);
                    ctx.stroke();
                }
            }

            // 2. Particle-to-Particle Connections
            for (let j = i + 1; j < particles.length; j++) {
                const p2 = particles[j];
                const dx = p1.x - p2.x;
                const dy = p1.y - p2.y;
                const dist = Math.sqrt(dx * dx + dy * dy);

                if (dist < connectionDistance) {
                    // Connection Line - White/Grey subtle
                    const opacity = 1 - (dist / connectionDistance);

                    // Premium touch: smoother opacity curve
                    const smoothOpacity = opacity * opacity;

                    ctx.strokeStyle = `rgba(255, 255, 255, ${smoothOpacity * 0.15})`; // White subtle
                    ctx.lineWidth = 0.5;
                    ctx.beginPath();
                    ctx.moveTo(p1.x, p1.y);
                    ctx.lineTo(p2.x, p2.y);
                    ctx.stroke();
                }
            }
        }

        requestAnimationFrame(animate);
    }

    // Reset on resize
    window.addEventListener('resize', resize);

    // Start
    resize();
    animate();
}


/**
 * Initializes a 3D Vehicle Viewer
 */
function initVehicle3DViewer(canvasId, modelPath, sceneKey) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

    // Check for THREE.js
    if (typeof THREE === 'undefined') {
        console.error('THREE.js is not loaded. 3D Viewer cannot be initialized.');
        return;
    }
    // Check for OBJLoader
    if (typeof THREE.OBJLoader === 'undefined') {
        console.error('THREE.OBJLoader is not loaded. 3D Viewer cannot be initialized.');
        return;
    }
    // Check for OrbitControls
    if (typeof THREE.OrbitControls === 'undefined') {
        console.error('THREE.OrbitControls is not loaded. 3D Viewer cannot be initialized.');
        return;
    }

    const placeholderImg = canvas.querySelector('.model-placeholder');

    const loadingDiv = document.createElement('div');
    loadingDiv.className = 'model-loading-overlay';
    loadingDiv.innerHTML = `
      <div class="loading-text">Loading 3D Model...</div>
      <div class="loading-progress">
        <div class="progress-bar" id="progress-${sceneKey}"></div>
      </div>
      <div class="loading-percent" id="percent-${sceneKey}">0%</div>
    `;
    canvas.appendChild(loadingDiv);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, canvas.clientWidth / canvas.clientHeight, 0.1, 1000);
    const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });

    renderer.setSize(canvas.clientWidth, canvas.clientHeight);
    renderer.setClearColor(0x000000, 0);
    renderer.shadowMap.enabled = true;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 2.0; /* Increased exposure for brighter render */
    canvas.appendChild(renderer.domElement);
    renderer.domElement.style.opacity = '0';

    /* Enhanced lighting for aluminium visibility */
    const ambientLight = new THREE.AmbientLight(0xffffff, 1.2); /* Brighter ambient */
    scene.add(ambientLight);

    const mainLight = new THREE.DirectionalLight(0xffffff, 1.8); /* Brighter main light */
    mainLight.position.set(5, 10, 7);
    scene.add(mainLight);

    /* Add fill light from opposite side */
    const fillLight = new THREE.DirectionalLight(0xaaccff, 1.0); /* Slight blue tint for metallic look */
    fillLight.position.set(-5, 5, -5);
    scene.add(fillLight);

    /* Add rim light for edge definition */
    const rimLight = new THREE.DirectionalLight(0xffffff, 0.8);
    rimLight.position.set(0, -5, 10);
    scene.add(rimLight);

    /* Add top light */
    const topLight = new THREE.DirectionalLight(0xffffff, 0.6);
    topLight.position.set(0, 15, 0);
    scene.add(topLight);

    const loader = new THREE.OBJLoader();
    loader.load(
        modelPath,
        function (object) {
            object.traverse(function (child) {
                if (child instanceof THREE.Mesh) {
                    child.material = new THREE.MeshStandardMaterial({
                        color: 0xDBDBDB, /* Brighter Silver/Aluminium */
                        metalness: 1.0,  /* Full metallic */
                        roughness: 0.1,  /* Very smooth for sharp highlights */
                        emissive: 0x222222, /* Subtle glow to prevent total blackness */
                    });
                    child.castShadow = true;
                    child.receiveShadow = true;
                }
            });

            if (sceneKey === 'vehicle3D_pathfinder') {
                object.rotation.x = Math.PI / 2;
                object.rotation.y = Math.PI;
            }

            const box = new THREE.Box3().setFromObject(object);
            const center = box.getCenter(new THREE.Vector3());
            const size = box.getSize(new THREE.Vector3());
            const maxDim = Math.max(size.x, size.y, size.z);
            const scale = 2 / maxDim;

            object.scale.set(scale, scale, scale);
            object.position.sub(center.multiplyScalar(scale));

            scene.add(object);

            loadingDiv.style.opacity = '0';
            if (placeholderImg) {
                placeholderImg.style.opacity = '0';
            }

            setTimeout(() => {
                loadingDiv.remove();
                if (placeholderImg) {
                    placeholderImg.remove();
                }
                renderer.domElement.style.transition = 'opacity 0.5s';
                renderer.domElement.style.opacity = '1';
            }, 300);
        },
        function (xhr) {
            const percentComplete = xhr.total > 0 ? (xhr.loaded / xhr.total * 100).toFixed(0) : 0;
            const progressBar = document.getElementById(`progress-${sceneKey}`);
            const percentText = document.getElementById(`percent-${sceneKey}`);
            if (progressBar) progressBar.style.width = percentComplete + '%';
            if (percentText) percentText.textContent = percentComplete + '%';
        },
        function (error) {
            console.error(`Error loading ${modelPath}:`, error);
            loadingDiv.innerHTML = '<div class="loading-error">Failed to load 3D model</div>';
        }
    );

    camera.position.set(0, 1, 4);
    camera.lookAt(0, 0, 0);

    const controls = new THREE.OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.05;
    controls.minDistance = 2;
    controls.maxDistance = 10;
    controls.maxPolarAngle = Math.PI / 1.5;
    controls.autoRotate = true;
    controls.autoRotateSpeed = 1.5;

    function animate() {
        requestAnimationFrame(animate);
        controls.update();
        renderer.render(scene, camera);
    }
    animate();

    window.addEventListener('resize', () => {
        const width = canvas.clientWidth;
        const height = canvas.clientHeight;
        camera.aspect = width / height;
        camera.updateProjectionMatrix();
        renderer.setSize(width, height);
    }, { passive: true });

    scenes[sceneKey] = { scene, renderer, camera, controls };
}

/**
 * Smooth scroll for navigation anchors
 */
function initSmoothScroll() {
    document.querySelectorAll('a[href^="#"]').forEach((anchor) => {
        anchor.addEventListener("click", function (e) {
            const href = this.getAttribute("href");
            // Only prevent default for hash links on the same page
            if (href.startsWith('#') && href.length > 1) {
                const target = document.querySelector(href);
                if (target) {
                    e.preventDefault();
                    target.scrollIntoView({
                        behavior: "smooth",
                        block: "start",
                    });
                }
            }
        });
    });
}

/**
 * Hamburger menu toggle
 */
function initHamburgerMenu() {
    const hamburger = document.querySelector(".hamburger");
    const navMenu = document.querySelector(".nav-menu");

    if (hamburger && navMenu) {
        hamburger.addEventListener("click", () => {
            navMenu.classList.toggle("active");
            hamburger.classList.toggle("active"); // NEW: Toggles "X" animation
        });

        // Close menu when a link is clicked
        document.querySelectorAll(".nav-link").forEach((link) => {
            link.addEventListener("click", () => {
                navMenu.classList.remove("active");
                hamburger.classList.remove("active"); // NEW: Removes "X" animation
            });
        });
    }
}

/**
 * Typing animation for hero text
 */
function initTypingAnimation() {
    const mainEl = document.getElementById("typing-main");
    const subEl = document.getElementById("typing-text");
    if (!mainEl || !subEl) return;

    const mainText = "Intelligence";
    const phrases = ["in Motion.", "Everywhere.", "Unstoppable."];
    let mainIndex = 0, subIndex = 0, phraseIndex = 0, isDeleting = false;
    const typeSpeed = 90, delSpeed = 45, pause = 2000;

    function typeMain() {
        mainEl.textContent = mainText.substring(0, mainIndex + 1);
        mainIndex++;
        if (mainIndex <= mainText.length) {
            setTimeout(typeMain, typeSpeed);
        } else {
            setTimeout(typeSub, pause / 2); // Start sub-typing sooner
        }
    }

    function typeSub() {
        const current = phrases[phraseIndex];
        let speed = isDeleting ? delSpeed : typeSpeed + Math.random() * 50;

        if (isDeleting) {
            subEl.textContent = current.substring(0, subIndex - 1);
            subIndex--;
            if (subIndex === 0) {
                isDeleting = false;
                phraseIndex = (phraseIndex + 1) % phrases.length;
                speed = 500; // Pause before new phrase
            }
        } else {
            subEl.textContent = current.substring(0, subIndex + 1);
            subIndex++;
            if (subIndex === current.length) {
                isDeleting = true;
                speed = pause; // Pause at end of phrase
            }
        }
        setTimeout(typeSub, speed);
    }

    typeMain(); // Start the chain
}

/**
 * MODIFIED: Starts loading 3D models immediately on page load
 */
function init3DModelLoading() { // Renamed from setupLazy3DLoading
    const canvas1 = document.getElementById('vehicle3DCanvas1');
    const canvas2 = document.getElementById('vehicle3DCanvas2');

    // Check if the canvases exist on this specific page

    if (canvas1) {
        // Start loading R1 immediately
        initVehicle3DViewer('vehicle3DCanvas1', 'Assets/objects/NR1.obj', 'vehicle3D_scout');
    }

    if (canvas2) {
        // Start loading TRAx immediately
        initVehicle3DViewer('vehicle3DCanvas2', 'Assets/objects/NTRAX.obj', 'vehicle3D_pathfinder');
    }
}

/**
 * Lazy load and auto-play video on scroll
 */
function initVideoShowcase() {
    const videoContainer = document.getElementById('showcase');
    if (!videoContainer) return;

    const players = videoContainer.querySelectorAll('.video-bg-element');
    const buttons = videoContainer.querySelectorAll('.video-select-btn');
    const playPauseBtn = document.getElementById('video-play-pause-btn');
    const playIcon = document.getElementById('icon-play');
    const pauseIcon = document.getElementById('icon-pause');
    let activePlayer = videoContainer.querySelector('.video-bg-element.active') || players[0];

    // Video switching
    buttons.forEach(btn => {
        btn.addEventListener('click', () => {
            const key = btn.dataset.videoKey;
            const newPlayer = videoContainer.querySelector(`.video-bg-element[data-key="${key}"]`);

            if (newPlayer && newPlayer !== activePlayer) {
                // Deactivate old
                buttons.forEach(b => b.classList.remove('active'));
                activePlayer.classList.remove('active');
                activePlayer.pause();

                // Activate new
                btn.classList.add('active');
                newPlayer.classList.add('active');
                newPlayer.play().catch(() => { });
                activePlayer = newPlayer;

                // Update play/pause icon
                if (playIcon && pauseIcon) {
                    playIcon.style.display = 'none';
                    pauseIcon.style.display = 'block';
                }
            }
        });
    });

    // Play/Pause button
    if (playPauseBtn && activePlayer) {
        playPauseBtn.addEventListener('click', () => {
            if (activePlayer.paused) {
                activePlayer.play().catch(() => { });
                if (playIcon && pauseIcon) {
                    playIcon.style.display = 'none';
                    pauseIcon.style.display = 'block';
                }
            } else {
                activePlayer.pause();
                if (playIcon && pauseIcon) {
                    playIcon.style.display = 'block';
                    pauseIcon.style.display = 'none';
                }
            }
        });
    }

    // Intersection observer for auto-play/pause
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                activePlayer.play().catch(() => { });
                if (playIcon && pauseIcon) {
                    playIcon.style.display = 'none';
                    pauseIcon.style.display = 'block';
                }
            } else {
                activePlayer.pause();
                if (playIcon && pauseIcon) {
                    playIcon.style.display = 'block';
                    pauseIcon.style.display = 'none';
                }
            }
        });
    }, { threshold: 0.5 });

    observer.observe(videoContainer);
}

/**
 * Scroll animations for fading in elements
 */
function initScrollAnimations() {
    const observerOptions = {
        threshold: 0.1,
        rootMargin: '0px 0px -100px 0px',
    };

    const observer = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
            if (entry.isIntersecting) {
                // Animate IN
                entry.target.style.opacity = "1";
                entry.target.style.transform = "translateY(0)";
            } else {
                // Animate OUT (This is the code I am re-enabling)
                entry.target.style.opacity = "0";
                entry.target.style.transform = "translateY(30px)";
            }
        });
    }, observerOptions);

    // Apply to all glass cards and feature items
    document.querySelectorAll(".glass-card, .feature-item").forEach((el) => {
        el.style.opacity = "0";
        el.style.transform = "translateY(30px)";
        el.style.transition = "all 0.6s cubic-bezier(0.4, 0, 0.2, 1)";
        el.style.willChange = "transform, opacity"; // Performance hint
        observer.observe(el);
    });
}

/**
 * Architecture Diagram Scroll Animations
 * Animates rows with staggered delays on scroll (both directions)
 */
function initArchitectureScrollAnimations() {
    const archDiagram = document.querySelector('.architecture-diagram.new-layout');
    if (!archDiagram) return;

    const archRows = archDiagram.querySelectorAll('.arch-row');

    // Initialize rows in hidden state
    archRows.forEach((row, index) => {
        row.style.opacity = "0";
        row.style.transform = "translateX(-40px)";
        row.style.transition = `all 0.5s cubic-bezier(0.4, 0, 0.2, 1) ${index * 0.08}s`;
        row.style.willChange = "transform, opacity";
    });

    const observerOptions = {
        threshold: 0.15,
        rootMargin: '0px 0px -50px 0px',
    };

    const observer = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
            if (entry.isIntersecting) {
                // Animate IN - cascade from left
                archRows.forEach((row, index) => {
                    setTimeout(() => {
                        row.style.opacity = "1";
                        row.style.transform = "translateX(0)";
                    }, index * 80);
                });
            } else {
                // Animate OUT - cascade reverse
                archRows.forEach((row, index) => {
                    const reverseIndex = archRows.length - 1 - index;
                    setTimeout(() => {
                        row.style.opacity = "0";
                        row.style.transform = "translateX(-40px)";
                    }, reverseIndex * 50);
                });
            }
        });
    }, observerOptions);

    observer.observe(archDiagram);

    // Also animate individual blocks within rows on hover for extra polish
    const blocks = archDiagram.querySelectorAll('.arch-block:not(.category-label):not(.invisible-block)');
    blocks.forEach((block) => {
        block.addEventListener('mouseenter', () => {
            block.style.transform = "translateY(-3px) scale(1.02)";
        });
        block.addEventListener('mouseleave', () => {
            block.style.transform = "translateY(0) scale(1)";
        });
    });
}

/**
 * Initializes tabbed interfaces (for Products/Services)
 */
function initTabs() {
    const allTabContainers = document.querySelectorAll('.tabs-container');

    // Video section elements for products page
    const productVideoGroups = document.querySelectorAll('.product-video-group');
    const videoSectionTitle = document.querySelector('.video-section-title');

    // Video title mapping
    const videoTitleMap = {
        'product-tab-ugv': 'Autonomous UGV In Action',
        'product-tab-sensor': 'Sensor Suite In Action',
        'product-tab-trax': 'TRAx Controller In Action',
        'product-tab-sim': 'HyperSim In Action'
    };

    allTabContainers.forEach(container => {
        const tabLinks = container.querySelectorAll(':scope > .tab-nav .tab-link, :scope > .sub-tab-nav .tab-link');
        const tabContents = container.querySelectorAll(':scope > .tab-content-wrapper > .tab-content');

        if (!tabLinks.length || !tabContents.length) return;

        tabLinks.forEach(link => {
            link.addEventListener('click', () => {
                const tabId = link.dataset.tab;

                // Deactivate all links in this group
                tabLinks.forEach(l => l.classList.remove('active'));
                // Deactivate all content in this group
                tabContents.forEach(c => c.classList.remove('active'));

                // Activate clicked link and corresponding content
                link.classList.add('active');
                const activeContent = container.querySelector(`#${tabId}`);
                if (activeContent) {
                    activeContent.classList.add('active');
                }

                // Update video section if this is a main product tab
                if (productVideoGroups.length && videoTitleMap[tabId]) {
                    // Hide all video groups
                    productVideoGroups.forEach(group => {
                        group.classList.remove('active');
                        // Reset scroll animations for hidden groups
                        group.querySelectorAll('.fullwidth-video-wrapper').forEach(wrapper => {
                            wrapper.classList.remove('visible');
                        });
                    });

                    // Show the matching video group
                    const activeVideoGroup = document.querySelector(`.product-video-group[data-product="${tabId}"]`);
                    if (activeVideoGroup) {
                        activeVideoGroup.classList.add('active');
                        // Trigger scroll check to animate visible videos
                        setTimeout(() => {
                            window.dispatchEvent(new Event('scroll'));
                        }, 100);
                    }

                    // Update the section title
                    if (videoSectionTitle) {
                        videoSectionTitle.textContent = videoTitleMap[tabId];
                    }
                }
            });
        });
    });
}

/**
 * Initializes the interactive video grid (Overland-style)
 */
function initInteractiveVideoGrid() {
    const videoGrids = document.querySelectorAll('.interactive-video-grid');

    videoGrids.forEach(grid => {
        const boxes = grid.querySelectorAll('.video-grid-box');
        const videoContainer = grid.querySelector('.video-player-container');
        const videoPlayer = grid.querySelector('.grid-video-player');

        if (!boxes.length || !videoContainer || !videoPlayer) return;

        let hoverTimeout;
        let currentBoxIndex = -1;
        const boxArray = Array.from(boxes);

        // Activate a specific box by index
        function activateBox(index) {
            if (index < 0 || index >= boxArray.length || index === currentBoxIndex) return;

            const box = boxArray[index];
            const videoUrl = box.dataset.video;
            if (!videoUrl) return;

            currentBoxIndex = index;

            // Add active state to grid
            grid.classList.add('video-active');

            // Mark this box as active
            boxes.forEach(b => b.classList.remove('active-box'));
            box.classList.add('active-box');

            // Set position based on index
            const positions = ['top-left', 'top-right', 'bottom-left', 'bottom-right'];
            box.setAttribute('data-position', positions[index % 4] || 'top-left');

            // Load and play video (native HTML5 video)
            if (videoPlayer.src !== videoUrl) {
                videoPlayer.src = videoUrl;
            }
            videoPlayer.play().catch(() => { });
        }

        // Get box index from mouse position on video container
        function getBoxIndexFromPosition(e) {
            const rect = grid.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;
            const width = rect.width;
            const height = rect.height;

            // Determine which quadrant
            const col = x < width / 2 ? 0 : 1;
            const row = y < height / 2 ? 0 : 1;

            // Map to box index (4 boxes in 2x2 grid)
            // Top row: 0, 1  Bottom row: 2, 3
            return row * 2 + col;
        }

        boxes.forEach((box, index) => {
            box.addEventListener('mouseenter', () => {
                clearTimeout(hoverTimeout);
                activateBox(index);
            });
        });

        // Track mouse movement over video container to switch boxes
        videoContainer.addEventListener('mousemove', (e) => {
            clearTimeout(hoverTimeout);
            const targetIndex = getBoxIndexFromPosition(e);
            if (targetIndex !== currentBoxIndex && targetIndex < boxArray.length) {
                activateBox(targetIndex);
            }
        });

        videoContainer.addEventListener('mouseenter', () => {
            clearTimeout(hoverTimeout);
        });

        grid.addEventListener('mouseleave', () => {
            hoverTimeout = setTimeout(() => {
                resetGrid();
            }, 200);
        });

        function resetGrid() {
            grid.classList.remove('video-active');
            boxes.forEach(b => {
                b.classList.remove('active-box');
                b.removeAttribute('data-position');
            });
            videoPlayer.pause();
            videoPlayer.src = '';
            currentBoxIndex = -1;
        }
    });
}

/**
 * Full-Width Video Showcase - Scroll Reveal & Autoplay
 */
function initFullWidthVideoShowcase() {
    const videoWrappers = document.querySelectorAll('.fullwidth-video-wrapper[data-scroll-reveal]');
    if (!videoWrappers.length) return;

    const observerOptions = {
        threshold: 0.2,
        rootMargin: '0px 0px -50px 0px',
    };

    const observer = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
            const video = entry.target.querySelector('.fullwidth-video');

            if (entry.isIntersecting) {
                // Reveal animation
                entry.target.classList.add('visible');
                // Play video
                if (video) {
                    video.play().catch(() => { });
                }
            } else {
                // Hide animation (for scroll up/down)
                entry.target.classList.remove('visible');
                // Pause video when out of view
                if (video) {
                    video.pause();
                }
            }
        });
    }, observerOptions);

    videoWrappers.forEach((wrapper) => {
        observer.observe(wrapper);
    });
}


/**
 * DOMContentLoaded - Main execution
 */
document.addEventListener('DOMContentLoaded', () => {
    // Init 3D background first
    initBackground3D();

    // Init UI components
    initSmoothScroll();
    initHamburgerMenu();
    initTypingAnimation();
    initScrollAnimations(); // This now handles the two-way animation
    initArchitectureScrollAnimations(); // Architecture diagram scroll animations
    initTabs(); // For product/service pages

    // Init loading components
    init3DModelLoading(); // Eager loading 3D models
    initVideoShowcase(); // For homepage video wall
    initFullWidthVideoShowcase(); // For full-width video showcase on products page

    // Init Lucide Icons if available
    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }
});