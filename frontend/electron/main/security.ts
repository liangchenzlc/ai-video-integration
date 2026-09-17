export function allowedPage(url: string, development: boolean): boolean {
  return development ? url === "http://127.0.0.1:5173/" : url === "app://ui/";
}
export const productionCsp =
  "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data: avi-media:; media-src avi-media:; font-src 'self'; connect-src 'none'; base-uri 'none'; form-action 'none'; frame-src 'none'; object-src 'none'";
export const developmentCsp =
  "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: avi-media:; media-src avi-media:; font-src 'self'; connect-src http://127.0.0.1:5173 ws://127.0.0.1:5173; base-uri 'none'; form-action 'none'; frame-src 'none'; object-src 'none'";
export function isTrustedSender(
  senderId: number,
  expectedId: number,
  isMainFrame: boolean,
  url: string,
  development: boolean,
): boolean {
  return (
    senderId === expectedId && isMainFrame && allowedPage(url, development)
  );
}
