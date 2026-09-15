import * as ImageManipulator from "expo-image-manipulator";

const MAX_LONGEST_EDGE = 1280;
const JPEG_COMPRESS_QUALITY = 0.9;

// Coin dates, mint marks, and wear detail matter for identification - this only
// caps runaway resolutions, it never produces a low-res thumbnail.
export async function prepareImageForIdentification(photo) {
  if (!photo?.base64 || !photo?.uri) return photo;

  const longestEdge = Math.max(photo.width || 0, photo.height || 0);
  if (!longestEdge || longestEdge <= MAX_LONGEST_EDGE) {
    return photo;
  }

  const resize = photo.width >= photo.height
    ? { width: MAX_LONGEST_EDGE }
    : { height: MAX_LONGEST_EDGE };

  const manipulated = await ImageManipulator.manipulateAsync(
    photo.uri,
    [{ resize }],
    { compress: JPEG_COMPRESS_QUALITY, format: ImageManipulator.SaveFormat.JPEG, base64: true }
  );

  return {
    ...photo,
    uri: manipulated.uri,
    base64: manipulated.base64,
    width: manipulated.width,
    height: manipulated.height,
  };
}
