import Link from "next/link";

// Next.js responde con 403 cuando una página llama a forbidden().
export default function Forbidden() {
  return (
    <main>
      <h1>No tienes acceso a esta sección</h1>
      <p>Si crees que es un error, pídele acceso a Alejo.</p>
      <p><Link href="/">Volver al inicio</Link></p>
    </main>
  );
}
