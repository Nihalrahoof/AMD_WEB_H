// ============================================
// AUTOMIND DYNAMICS - Premium JavaScript
// 3D Canvas & Interactive Elements
// ============================================

// Import Three.js
const THREE = window.THREE

// Initialize Three.js scenes
const scenes = {}

// Hero Canvas - Animated Background
function initHeroCanvas() {
  const canvas = document.getElementById("heroCanvas")
  if (!canvas) return

  const scene = new THREE.Scene()
  const camera = new THREE.PerspectiveCamera(75, window.innerWidth / (window.innerHeight - 60), 0.1, 1000)
  const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true })

  renderer.setSize(window.innerWidth, window.innerHeight - 60)
  renderer.setClearColor(0x000000, 0)
  renderer.shadowMap.enabled = true
  canvas.appendChild(renderer.domElement)

  // Create floating particles
  const particlesGeometry = new THREE.BufferGeometry()
  const particlesCount = 100
  const posArray = new Float32Array(particlesCount * 3)

  for (let i = 0; i < particlesCount * 3; i += 3) {
    posArray[i] = (Math.random() - 0.5) * 200
    posArray[i + 1] = (Math.random() - 0.5) * 200
    posArray[i + 2] = (Math.random() - 0.5) * 200
  }

  particlesGeometry.setAttribute("position", new THREE.BufferAttribute(posArray, 3))
  const particleMaterial = new THREE.PointsMaterial({
    size: 0.5,
    color: 0xec4899, // Pink particles to match the new theme
    sizeAttenuation: true,
  })
  const particles = new THREE.Points(particlesGeometry, particleMaterial)
  scene.add(particles)

  // Create sophisticated AI core with crystal-like structure
  const coreGroup = new THREE.Group()
  
  // Main crystal core - octahedron shape
  const coreGeometry = new THREE.OctahedronGeometry(0.8, 2)
  const coreMaterial = new THREE.MeshPhongMaterial({
    color: 0x9333ea, // Purple
    wireframe: false,
    emissive: 0x6b21d8,
    emissiveIntensity: 0.6,
    shininess: 150,
    transparent: true,
    opacity: 0.9,
  })
  const core = new THREE.Mesh(coreGeometry, coreMaterial)
  core.castShadow = true
  coreGroup.add(core)

  // Inner energy core - smaller glowing sphere
  const innerCoreGeometry = new THREE.SphereGeometry(0.3, 16, 16)
  const innerCoreMaterial = new THREE.MeshPhongMaterial({
    color: 0xfbbf24, // Gold
    emissive: 0xf59e0b,
    emissiveIntensity: 1.2,
    transparent: true,
    opacity: 0.8,
  })
  const innerCore = new THREE.Mesh(innerCoreGeometry, innerCoreMaterial)
  coreGroup.add(innerCore)

  // Create sophisticated orbiting structures
  // Outer ring with crystal segments
  const ring1Geometry = new THREE.TorusGeometry(1.8, 0.1, 8, 60)
  const ring1Material = new THREE.MeshPhongMaterial({
    color: 0xec4899, // Pink
    emissive: 0xdb2777,
    emissiveIntensity: 0.4,
    transparent: true,
    opacity: 0.8,
  })
  const ring1 = new THREE.Mesh(ring1Geometry, ring1Material)
  ring1.rotation.x = Math.PI / 4
  ring1.rotation.z = Math.PI / 8
  ring1.castShadow = true
  coreGroup.add(ring1)

  // Middle ring with different orientation
  const ring2Geometry = new THREE.TorusGeometry(2.5, 0.08, 8, 80)
  const ring2Material = new THREE.MeshPhongMaterial({
    color: 0x10b981, // Emerald green
    emissive: 0x059669,
    emissiveIntensity: 0.5,
    transparent: true,
    opacity: 0.7,
  })
  const ring2 = new THREE.Mesh(ring2Geometry, ring2Material)
  ring2.rotation.x = -Math.PI / 3
  ring2.rotation.y = Math.PI / 6
  ring2.castShadow = true
  coreGroup.add(ring2)

  // Add floating crystal shards
  const shardGeometry = new THREE.OctahedronGeometry(0.15, 0)
  const shardMaterial = new THREE.MeshPhongMaterial({
    color: 0x3b82f6, // Blue
    emissive: 0x2563eb,
    emissiveIntensity: 0.3,
    transparent: true,
    opacity: 0.8,
  })

  for (let i = 0; i < 8; i++) {
    const shard = new THREE.Mesh(shardGeometry, shardMaterial)
    const angle = (i / 8) * Math.PI * 2
    const radius = 3.2
    shard.position.x = Math.cos(angle) * radius
    shard.position.z = Math.sin(angle) * radius
    shard.position.y = (Math.random() - 0.5) * 1.5
    shard.rotation.x = Math.random() * Math.PI
    shard.rotation.y = Math.random() * Math.PI
    shard.rotation.z = Math.random() * Math.PI
    shard.castShadow = true
    coreGroup.add(shard)
  }

  scene.add(coreGroup)

  // Lighting - updated to match new color scheme
  const pointLight = new THREE.PointLight(0x9333ea, 2.0) // Purple light
  pointLight.position.set(8, 8, 8)
  pointLight.castShadow = true
  scene.add(pointLight)

  const ambientLight = new THREE.AmbientLight(0xffffff, 0.3)
  scene.add(ambientLight)

  const backLight = new THREE.PointLight(0xfbbf24, 1.5) // Gold light
  backLight.position.set(-8, -8, -8)
  scene.add(backLight)

  // Add colored accent lights
  const pinkLight = new THREE.PointLight(0xec4899, 1.0)
  pinkLight.position.set(0, 5, 0)
  scene.add(pinkLight)

  const greenLight = new THREE.PointLight(0x10b981, 0.8)
  greenLight.position.set(0, -5, 0)
  scene.add(greenLight)

  camera.position.z = 8

  // Animation loop
  function animate() {
    requestAnimationFrame(animate)

    // Rotate the entire core group slowly
    coreGroup.rotation.x += 0.001
    coreGroup.rotation.y += 0.002

    // Rotate individual elements at different speeds
    core.rotation.x += 0.003
    core.rotation.y += 0.005
    
    innerCore.rotation.x -= 0.004
    innerCore.rotation.y -= 0.006

    ring1.rotation.y += 0.008
    ring1.rotation.z += 0.002
    
    ring2.rotation.y -= 0.006
    ring2.rotation.x += 0.003

    // Animate floating shards
    coreGroup.children.forEach((child, index) => {
      if (child.material && child.material.color && child.material.color.getHex() === 0x3b82f6) {
        // This is a blue shard
        child.rotation.x += 0.01 + index * 0.002
        child.rotation.y += 0.015 + index * 0.003
        child.rotation.z += 0.008 + index * 0.001
        
        // Add floating motion
        const time = Date.now() * 0.001
        child.position.y += Math.sin(time + index) * 0.002
      }
    })

    particles.rotation.y += 0.0003
    particles.rotation.x += 0.0001

    renderer.render(scene, camera)
  }
  animate()

  // Handle window resize
  window.addEventListener("resize", () => {
    const newWidth = window.innerWidth
    const newHeight = window.innerHeight - 60
    camera.aspect = newWidth / newHeight
    camera.updateProjectionMatrix()
    renderer.setSize(newWidth, newHeight)
  })

  scenes.hero = { scene, renderer, camera }
}

// Vehicle Canvases
// Removed vehicle canvas initializers – now using static images

// Smooth scroll for navigation
document.querySelectorAll('a[href^="#"]').forEach((anchor) => {
  anchor.addEventListener("click", function (e) {
    e.preventDefault()
    const target = document.querySelector(this.getAttribute("href"))
    if (target) {
      target.scrollIntoView({
        behavior: "smooth",
        block: "start",
      })
    }
  })
})

// Hamburger menu toggle
const hamburger = document.querySelector(".hamburger")
const navMenu = document.querySelector(".nav-menu")

if (hamburger) {
  hamburger.addEventListener("click", () => {
    navMenu.classList.toggle("active")
  })

  // Close menu when link is clicked
  document.querySelectorAll(".nav-link").forEach((link) => {
    link.addEventListener("click", () => {
      navMenu.classList.remove("active")
    })
  })
}

// Typing animation for hero text
function initTypingAnimation() {
  const mainEl   = document.getElementById("typing-main");
  const subEl    = document.getElementById("typing-text");
  if (!mainEl || !subEl) return;

  const mainText = "Autonomy";
  const phrases  = ["Anywhere. Anytime.", "Everywhere. Everytime.", "Unlimited. Unstoppable."];

  let mainIndex = 0, subIndex = 0, phraseIndex = 0, isDeleting = false;
  const typeSpeed = 90, delSpeed = 45, pause = 2000;

  function typeMain() {
    mainEl.textContent = mainText.substring(0, mainIndex + 1);
    mainIndex++;
    if (mainIndex <= mainText.length) {
      setTimeout(typeMain, typeSpeed);
    } else {
      setTimeout(typeSub, pause);
    }
  }

  function typeSub() {
    const current = phrases[phraseIndex];
    if (isDeleting) {
      subEl.textContent = current.substring(0, subIndex - 1);
      subIndex--;
      if (subIndex === 0) {
        isDeleting = false;
        phraseIndex = (phraseIndex + 1) % phrases.length;
        setTimeout(typeSub, 500);
        return;
      }
    } else {
      subEl.textContent = current.substring(0, subIndex + 1);
      subIndex++;
      if (subIndex === current.length) {
        isDeleting = true;
        setTimeout(typeSub, pause);
        return;
      }
    }
    setTimeout(typeSub, isDeleting ? delSpeed : typeSpeed + Math.random() * 50);
  }

  typeMain();          // start the chain
}

// Initialize all canvases
document.addEventListener('DOMContentLoaded', () => {
  initHeroCanvas();
  initTypingAnimation();
  // Removed vehicle canvas initializers – now using static images

  // Scroll animations
  const observerOptions = {
    threshold: 0.1,
    rootMargin: '0px 0px -100px 0px',
  };

  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.style.opacity = "1"
        entry.target.style.transform = "translateY(0)"
      }
    })
  }, observerOptions)

  document.querySelectorAll(".glass-card, .feature-item").forEach((el) => {
    el.style.opacity = "0"
    el.style.transform = "translateY(30px)"
    el.style.transition = "all 0.6s cubic-bezier(0.4, 0, 0.2, 1)"
    observer.observe(el)
  })

  // CTA Button interactions
  document.querySelectorAll(".cta-button, .learn-btn").forEach((button) => {
    button.addEventListener("mouseenter", function () {
      if (!this.classList.contains("primary")) {
        this.style.transform = "translateY(-2px)"
      }
    })
    button.addEventListener("mouseleave", function () {
      this.style.transform = "translateY(0)"
    })
  })
})

// Handle window resize for responsive behavior
window.addEventListener("resize", () => {
  if (scenes.hero) {
    const newWidth = window.innerWidth
    const newHeight = window.innerHeight - 60
    scenes.hero.camera.aspect = newWidth / newHeight
    scenes.hero.camera.updateProjectionMatrix()
    scenes.hero.renderer.setSize(newWidth, newHeight)
  }
})

// Auto-play video on scroll
document.addEventListener('DOMContentLoaded', () => {
  const video = document.getElementById('showcase-video');
  if (!video) return;

  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        video.play().catch(() => {});   // auto-play muted video
      } else {
        video.pause();
      }
    });
  }, { threshold: 0.5 });

  observer.observe(video);
});
