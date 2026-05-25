const HX_HEADERS = { "HX-Request": "true" } as const;

export function postForm(url: string, data: FormData): Promise<Response> {
  return fetch(url, { method: "POST", body: data, headers: HX_HEADERS });
}

export async function getHtml(url: string): Promise<string> {
  const res = await fetch(url, { headers: HX_HEADERS });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.text();
}
