// Custom next/image loader: pass the src straight through.
//
// Remote thumbnails are presigned S3 URLs (signature changes per request,
// so Next's built-in optimizer can't cache them anyway) pointing at images
// the backend already pre-resizes to a fixed max 400x400
// (packages/transcoder/image_processor.py). There's nothing left for a
// resize/re-encode proxy to usefully do, so skip it — this also means we
// never need to allowlist a specific S3 provider's hostname in
// next.config.js, and switching storage providers needs no web changes.
export default function imageLoader({ src }: { src: string; width: number; quality?: number }): string {
  return src
}
