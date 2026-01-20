import React, { useRef, useMemo } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { useLoader } from '@react-three/fiber';
import { OBJLoader } from 'three/examples/jsm/loaders/OBJLoader';
import { useScroll } from '@react-three/drei';
import * as THREE from 'three';

const Model = () => {
  const obj = useLoader(OBJLoader, '/R1.obj');
  const ref = useRef();
  const scroll = useScroll();

  const geometry = useMemo(() => {
    let g;
    obj.traverse(c => {
      if (c.type === "Mesh") {
          g = c.geometry;
      }
    })
    return g;
  }, [obj])

  useFrame(() => {
    if (ref.current) {
      ref.current.rotation.y = scroll.offset * Math.PI * 2;
      ref.current.rotation.x = scroll.offset * Math.PI * 0.5;
    }
  });

  return (
    <mesh ref={ref} geometry={geometry}>
      <meshStandardMaterial color="#ff0000" />
    </mesh>
  );
};

const Scene = () => {
  return (
    <Canvas style={{ position: 'fixed', top: 0, left: 0, zIndex: -1 }}>
      <ambientLight intensity={0.5} />
      <spotLight position={[10, 10, 10]} angle={0.15} penumbra={1} />
      <pointLight position={[-10, -10, -10]} />
      <Model />
    </Canvas>
  );
};

export default Scene;
