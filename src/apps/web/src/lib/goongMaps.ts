const maptilesKey = (
  import.meta.env.GOONG_MAPTILES_KEY ?? import.meta.env.VITE_GOONG_MAPTILES_KEY ?? ""
).trim();

type GoongMapsNamespace = {
  accessToken: string;
  Map: new (options: Record<string, unknown>) => any;
  Marker: new (options?: Record<string, unknown>) => any;
  Popup: new (options?: Record<string, unknown>) => any;
  NavigationControl: new () => any;
  LngLatBounds: new () => any;
  supported: () => boolean;
};

declare global {
  interface Window {
    goongjs?: GoongMapsNamespace;
  }
}

export function goongMapsConfigured(): boolean {
  return Boolean(maptilesKey);
}

export function getGoongMaps(): GoongMapsNamespace {
  if (!maptilesKey) {
    throw new Error("Thiếu GOONG_MAPTILES_KEY nên chưa thể hiển thị bản đồ Goong.");
  }
  if (!window.goongjs) {
    throw new Error("Không tải được thư viện Goong JS từ CDN.");
  }
  window.goongjs.accessToken = maptilesKey;
  return window.goongjs;
}

export function getGoongStyleUrl(): string {
  if (!maptilesKey) {
    throw new Error("Thiếu GOONG_MAPTILES_KEY nên chưa thể tải style bản đồ Goong.");
  }
  return "https://tiles.goong.io/assets/goong_map_web.json";
}
