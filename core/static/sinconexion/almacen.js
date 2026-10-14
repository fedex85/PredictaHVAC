// Almacén local de órdenes descargadas. Dos implementaciones con la misma interfaz asíncrona:
// obtener(id), guardar(trabajo), borrar(id), listar().

const BASE = 'predicta-sinconexion';
const TABLA = 'ordenes';

export function almacenEnMemoria() {
  const datos = new Map();
  const copia = (v) => (v === undefined ? undefined : structuredClone(v));
  return {
    async obtener(id) { return copia(datos.get(id)); },
    async guardar(trabajo) { datos.set(trabajo.id, copia(trabajo)); },
    async borrar(id) { datos.delete(id); },
    async listar() { return [...datos.values()].map(copia); },
  };
}

function abrir(idb) {
  return new Promise((resolver, rechazar) => {
    const peticion = idb.open(BASE, 1);
    peticion.onupgradeneeded = () => {
      const bd = peticion.result;
      if (!bd.objectStoreNames.contains(TABLA)) bd.createObjectStore(TABLA, { keyPath: 'id' });
    };
    peticion.onsuccess = () => resolver(peticion.result);
    peticion.onerror = () => rechazar(peticion.error);
  });
}

// Cada operación espera a que la transacción termine (oncomplete): solo entonces el dato está guardado.
export function almacenIdb(idb = globalThis.indexedDB) {
  let bdPromesa = null;
  const bd = () => (bdPromesa ||= abrir(idb));
  async function operar(modo, accion) {
    const conexion = await bd();
    return new Promise((resolver, rechazar) => {
      const tx = conexion.transaction(TABLA, modo);
      const tabla = tx.objectStore(TABLA);
      let resultado;
      const peticion = accion(tabla);
      if (peticion) peticion.onsuccess = () => { resultado = peticion.result; };
      tx.oncomplete = () => resolver(resultado);
      tx.onerror = () => rechazar(tx.error);
      tx.onabort = () => rechazar(tx.error || new Error('Transacción cancelada'));
    });
  }
  return {
    obtener: (id) => operar('readonly', (t) => t.get(id)),
    guardar: (trabajo) => operar('readwrite', (t) => t.put(trabajo)),
    borrar: (id) => operar('readwrite', (t) => t.delete(id)),
    listar: async () => (await operar('readonly', (t) => t.getAll())) || [],
  };
}
