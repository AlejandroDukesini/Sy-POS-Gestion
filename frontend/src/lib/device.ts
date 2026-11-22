/**
 * Identidad del equipo (restricción de acceso por dispositivo).
 *
 * El equipo tiene un par de claves ECDSA P-256 creado con WebCrypto. La clave PRIVADA se crea NO exportable:
 * se guarda en IndexedDB como objeto CryptoKey y ni esta página ni un script pueden leer sus bytes. El servidor
 * solo recibe la clave pública y firmas de desafíos de un solo uso (prueba de posesión).
 *
 * Limitaciones (documentadas): requiere un contexto seguro (https o el propio equipo); borrar los datos del
 * navegador elimina la clave (el equipo debe autorizarse de nuevo); un navegador no identifica de forma
 * infalible un computador físico.
 */
import { post } from '../api/client';

const DB = 'pospy-equipo';
const STORE = 'claves';
const ID = 'equipo';

export interface DeviceProof { public_key: string; nonce: string; signature: string }

export function deviceSupported(): boolean {
  return typeof window !== 'undefined' && window.isSecureContext && Boolean(window.crypto?.subtle) && typeof indexedDB !== 'undefined';
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function readPair(): Promise<CryptoKeyPair | undefined> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const req = db.transaction(STORE, 'readonly').objectStore(STORE).get(ID);
    req.onsuccess = () => resolve(req.result as CryptoKeyPair | undefined);
    req.onerror = () => reject(req.error);
  });
}

async function writePair(pair: CryptoKeyPair): Promise<void> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, 'readwrite');
    tx.objectStore(STORE).put(pair, ID);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

let cached: Promise<CryptoKeyPair> | null = null;

/** Par de claves de este equipo (se crea la primera vez; la privada no es exportable). */
export function deviceKeys(): Promise<CryptoKeyPair> {
  if (!cached) {
    cached = (async () => {
      const existing = await readPair();
      if (existing?.privateKey && existing.publicKey) return existing;
      const pair = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, false, ['sign', 'verify']);
      await writePair(pair);
      return pair;
    })().catch((err) => { cached = null; throw err; });
  }
  return cached;
}

const b64 = (buf: ArrayBuffer) => btoa(String.fromCharCode(...new Uint8Array(buf)));

/** Firma un desafío nuevo del servidor con la clave de este equipo. */
export async function deviceProof(): Promise<DeviceProof> {
  if (!deviceSupported()) {
    throw new Error('Este navegador no puede identificar el equipo: abra el POS con su dirección segura (https).');
  }
  const pair = await deviceKeys();
  const { nonce } = await post<{ nonce: string }>('/devices/challenge', {});
  const signature = await crypto.subtle.sign({ name: 'ECDSA', hash: 'SHA-256' }, pair.privateKey, new TextEncoder().encode(nonce));
  const spki = await crypto.subtle.exportKey('spki', pair.publicKey);
  return { public_key: b64(spki), nonce, signature: b64(signature) };
}

/** Huella corta de la clave pública (para reconocer el equipo en la lista del administrador). */
export async function deviceFingerprint(): Promise<string> {
  const pair = await deviceKeys();
  const spki = await crypto.subtle.exportKey('spki', pair.publicKey);
  const hash = await crypto.subtle.digest('SHA-256', spki);
  return [...new Uint8Array(hash)].slice(0, 8).map((b) => b.toString(16).padStart(2, '0')).join('');
}

export function suggestedDeviceName(): string {
  const ua = navigator.userAgent;
  const os = /Windows/.test(ua) ? 'Windows' : /Android/.test(ua) ? 'Android' : /iPhone|iPad/.test(ua) ? 'iOS' : /Mac/.test(ua) ? 'Mac' : 'Equipo';
  const browser = /Edg\//.test(ua) ? 'Edge' : /Chrome\//.test(ua) ? 'Chrome' : /Firefox\//.test(ua) ? 'Firefox' : /Safari\//.test(ua) ? 'Safari' : 'navegador';
  return `${os} · ${browser}`;
}
