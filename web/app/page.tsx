import { redirect } from "next/navigation";
import { requireUser } from "@/lib/auth";

export default async function Home() {
  const me = await requireUser();
  if (me.isAdmin) redirect("/admin");
  return (
    <main>
      <h1>Daily Delivery</h1>
      <p>Hola. La pantalla para hacer tu reporte llega en la etapa 3.</p>
      <form action="/auth/salir" method="post"><button>Salir</button></form>
    </main>
  );
}
