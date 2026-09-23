import { manipulateAsync, SaveFormat } from "expo-image-manipulator";

// Vision models bill input images by tiling them into fixed-size chunks, so
// a full-resolution phone photo (often 3000-4000px on the long edge) costs
// far more tokens than a resized one without meaningfully improving coin
// identification. On a low OpenAI usage tier this can push a single
// two-image identify-coin request over the account's tokens-per-minute
// limit by itself. Capping the long edge keeps enough detail for mint
// marks/wear while keeping token cost predictable.
const MAX_DIMENSION = 1280;
const COMPRESS_QUALITY = 0.9;

// `photo` is a capture result from expo-camera's takePictureAsync or an
// expo-image-picker asset - both expose { uri, base64, width, height }.
export async function prepareImageForIdentification(photo) {
  const longEdge = Math.max(photo?.width || 0, photo?.height || 0);
  if (!photo?.uri || !longEdge || longEdge <= MAX_DIMENSION) {
    return photo?.base64;
  }

  const resizeAction = photo.width >= photo.height
    ? { resize: { width: MAX_DIMENSION } }
    : { resize: { height: MAX_DIMENSION } };

  const result = await manipulateAsync(photo.uri, [resizeAction], {
    base64: true,
    compress: COMPRESS_QUALITY,
    format: SaveFormat.JPEG,
  });

  return result.base64 || photo.base64;
}
