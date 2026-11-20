/** Inventario simulado para las pruebas de pantalla: el usuario simulado entra a uno con sus mismos permisos. */
let lastPermissions: string[] = [];

export function rememberPermissions(permissions: string[]) {
  lastPermissions = permissions;
}

export function isInventoriesList(url: string): boolean {
  return /\/api\/inventories(\?|$)/.test(url);
}

export function inventoryList(permissions: string[] = lastPermissions) {
  return [{
    key: 'I-TEST0001', name: 'Inventario principal', description: '', status: 'activo', group: null, owner: false,
    products: 0, stock: '0', low_stock: 0, last_update: null, first_products: [], permissions,
  }];
}
