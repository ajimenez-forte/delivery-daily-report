import Link from "next/link";
import { requireAdmin } from "@/lib/auth";

// Toda la sección exige rol admin en el servidor (403 si no lo es). RLS aplica igual en la base.
export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  const me = await requireAdmin();
  return (
    <>
      <header className="top">
        <strong>Daily Delivery</strong>
        <nav>
          <Link href="/admin/boletin">Boletín del día</Link>
          <Link href="/admin/carga">Carga y cumplimiento</Link>
          <Link href="/admin/revision">Revisión</Link>
          <Link href="/admin/usuarios">Usuarios</Link>
          <Link href="/admin">Importación</Link>
        </nav>
        <span className="who">
          {me.email}
          <form action="/auth/salir" method="post"><button>Salir</button></form>
        </span>
      </header>
      <main>{children}</main>
    </>
  );
}
