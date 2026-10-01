import { GoogleButton } from "./GoogleButton";

export default async function Login({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  const { error } = await searchParams;
  return (
    <main>
      <h1>Daily Delivery</h1>
      <p>Entra con tu cuenta de Google @forteglobal.com.</p>
      {error ? <p className="danger">No se pudo iniciar sesión. Solo pueden entrar las cuentas @forteglobal.com de la lista de acceso.</p> : null}
      <GoogleButton />
    </main>
  );
}
