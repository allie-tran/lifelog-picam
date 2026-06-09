import React, { useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  FlatList,
  Image,
  Modal,
  PermissionsAndroid,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import WebView from 'react-native-webview';
import Video, { VideoRef } from 'react-native-video';
import { CameraRoll } from '@react-native-camera-roll/camera-roll';
import RNShare from 'react-native-share';
import RNFS from 'react-native-fs';
import { config, COLORS, formatTimeTz, formatDateTimeTz } from '../constants';
import { ImageObject } from '../types';
import { useAppDispatch, useAppSelector } from '../store';
import { addSubmission } from '../store/slices/dresSlice';
import { submitImageToDRES, SubmitVerdict } from '../api/dres';
import { deleteImage, similarImages, getImageMetadata, ImageMetadata } from '../api/browsing';

interface Props {
  image: ImageObject;
  deviceId: string;
  size?: number;
}

const VERDICT_COLOR: Record<SubmitVerdict, string> = {
  CORRECT: '#155724', INCORRECT: '#721c24', INDETERMINATE: '#856404',
  INVALID: '#721c24', ERROR: '#383d41',
};
const VERDICT_BG: Record<SubmitVerdict, string> = {
  CORRECT: '#d4edda', INCORRECT: '#f8d7da', INDETERMINATE: '#fff3cd',
  INVALID: '#f8d7da', ERROR: '#e2e3e5',
};

const thumbUri = (img: ImageObject, deviceId: string, log: boolean = false) => {
  const uri = img.thumbnail ? `${config.imageUrl}/${deviceId}/${img.thumbnail}` : null;
  return uri;
};

const fullUri = (img: ImageObject, deviceId: string) =>
  `${config.backendUrl}/get-image?device=${encodeURIComponent(deviceId)}&filename=${encodeURIComponent(img.imagePath)}`;

const requestMediaPermission = async () => {
  if (Platform.OS !== 'android') { return true; }
  if (Platform.Version >= 33) {
    const granted = await PermissionsAndroid.requestMultiple([
      PermissionsAndroid.PERMISSIONS.READ_MEDIA_IMAGES,
      PermissionsAndroid.PERMISSIONS.READ_MEDIA_VIDEO,
    ]);
    return Object.values(granted).every(v => v === PermissionsAndroid.RESULTS.GRANTED);
  }
  const result = await PermissionsAndroid.request(PermissionsAndroid.PERMISSIONS.WRITE_EXTERNAL_STORAGE);
  return result === PermissionsAndroid.RESULTS.GRANTED;
};

const ImageCard = ({ image, deviceId, size = 110 }: Props) => {
  const dispatch = useAppDispatch();
  const { sessionId, evaluationId } = useAppSelector(s => s.dres);
  const token = useAppSelector(s => s.auth.token);
  const dresReady = !!sessionId && !!evaluationId;

  const [deleted, setDeleted] = useState(false);
  const [zoomed, setZoomed] = useState(false);
  const [currentImg, setCurrentImg] = useState<ImageObject>(image);
  const [submitting, setSubmitting] = useState(false);
  const [verdict, setVerdict] = useState<{ v: SubmitVerdict; msg: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const [paused, setPaused] = useState(true);
  const videoRef = useRef<VideoRef>(null);

  // Similar images
  const [similarImgs, setSimilarImgs] = useState<ImageObject[]>([]);
  const [loadingSimilar, setLoadingSimilar] = useState(false);
  const [showSimilar, setShowSimilar] = useState(false);

  // Metadata (location, GPS, people, objects)
  const [metadata, setMetadata] = useState<ImageMetadata | null>(null);
  const [loadingMeta, setLoadingMeta] = useState(false);
  const [showInfo, setShowInfo] = useState(false);
  const [showBBoxes, setShowBBoxes] = useState(true);

  useEffect(() => {
    if (!zoomed || metadata || loadingMeta) { return; }
    setLoadingMeta(true);
    getImageMetadata(deviceId, currentImg.imagePath)
      .then(res => setMetadata(res.data))
      .catch(() => {})
      .finally(() => setLoadingMeta(false));
  }, [zoomed]);

  if (deleted) { return null; }

  const uri = thumbUri(image, deviceId);
  const authHeaders: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {};

  const handleClose = () => {
    setZoomed(false);
    setVerdict(null);
    setShowSimilar(false);
    setSimilarImgs([]);
    setCurrentImg(image);
    setPaused(true);
    setShowInfo(false);
    setMetadata(null);
    setShowBBoxes(true);
  };

  const handleSubmitToDRES = async () => {
    if (!sessionId || !evaluationId) { return; }
    setSubmitting(true);
    setVerdict(null);
    try {
      const result = await submitImageToDRES(currentImg.imagePath, evaluationId, sessionId);
      setVerdict({ v: result.verdict, msg: result.message });
      dispatch(addSubmission({
        type: 'image',
        content: currentImg.imagePath.split('/').pop() ?? currentImg.imagePath,
        verdict: result.verdict,
        message: result.message,
        ts: new Date().toISOString(),
      }));
    } catch {
      setVerdict({ v: 'ERROR', msg: 'Submission failed' });
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = () => {
    Alert.alert('Delete image', 'Move this image to trash?', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Delete', style: 'destructive', onPress: async () => {
          try {
            await deleteImage(deviceId, currentImg.imagePath);
            handleClose();
            setDeleted(true);
          } catch {
            Alert.alert('Error', 'Failed to delete image.');
          }
        },
      },
    ]);
  };

  const handleFindSimilar = async () => {
    setShowSimilar(true);
    if (similarImgs.length > 0) { return; }
    setLoadingSimilar(true);
    try {
      const res = await similarImages(deviceId, currentImg.imagePath);
      setSimilarImgs(res.data ?? []);
    } catch {
      setSimilarImgs([]);
    } finally {
      setLoadingSimilar(false);
    }
  };

  // Download file to a temp path, returns the path
  const downloadToTemp = async (): Promise<string> => {
    const ext = currentImg.isVideo ? 'mp4' : 'jpg';
    const destPath = `${RNFS.TemporaryDirectoryPath}/lifelog_${Date.now()}.${ext}`;
    const { promise } = RNFS.downloadFile({
      fromUrl: fullUri(currentImg, deviceId),
      toFile: destPath,
      headers: authHeaders as Record<string, string>,
    });
    await promise;
    return destPath;
  };

  const handleSave = async () => {
    const ok = await requestMediaPermission();
    if (!ok) {
      Alert.alert('Permission required', 'Allow media access to save images.');
      return;
    }
    setSaving(true);
    try {
      const path = await downloadToTemp();
      const fileUri = Platform.OS === 'android' ? `file://${path}` : path;
      await CameraRoll.saveAsset(fileUri, {
        type: currentImg.isVideo ? 'video' : 'photo',
        album: 'Lifelog',
      });
      RNFS.unlink(path).catch(() => {});
      Alert.alert('Saved', `${currentImg.isVideo ? 'Video' : 'Photo'} saved to gallery.`);
    } catch (e: any) {
      Alert.alert('Save failed', e?.message ?? 'Could not save file.');
    } finally {
      setSaving(false);
    }
  };

  const handleShare = async () => {
    setSaving(true);
    try {
      const path = await downloadToTemp();
      const mimeType = currentImg.isVideo ? 'video/mp4' : 'image/jpeg';
      const fileUri = Platform.OS === 'android' ? `file://${path}` : path;
      await RNShare.open({ url: fileUri, type: mimeType });
      RNFS.unlink(path).catch(() => {});
    } catch (e: any) {
      if (e?.message !== 'User did not share') {
        Alert.alert('Share failed', e?.message ?? 'Could not share file.');
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <TouchableOpacity onPress={() => setZoomed(true)} style={[styles.card, { width: size, height: size }]}>
        {uri ? (
          <Image source={{ uri }} style={styles.image} resizeMode="cover" />
        ) : (
          <View style={[styles.image, styles.placeholder]}>
            <Text style={styles.placeholderText}>{formatTimeTz(image.timestamp, image.timezone || config.defaultTimezone)}</Text>
          </View>
        )}
        {/* Video play indicator */}
        {image.isVideo && (
          <View style={styles.playOverlay}>
            <Text style={styles.playIcon}>▶</Text>
          </View>
        )}
        <View style={styles.badge}>
          <Text style={styles.badgeText}>{formatTimeTz(image.timestamp, image.timezone || config.defaultTimezone)}</Text>
        </View>
      </TouchableOpacity>

      <Modal visible={zoomed} transparent animationType="fade" onRequestClose={handleClose}>
        <TouchableOpacity style={styles.overlay} activeOpacity={1} onPress={handleClose}>

          {/* Image / video with bbox overlay */}
          <ZoomedImageWithBBoxes
            img={currentImg}
            deviceId={deviceId}
            authHeaders={authHeaders}
            paused={paused}
            setPaused={setPaused}
            videoRef={videoRef}
            metadata={metadata}
            showBBoxes={showBBoxes}
            containerStyle={showSimilar ? styles.zoomedImageSmall : styles.zoomedImage}
          />

          {/* Meta */}
          <View style={styles.zoomedMeta}>
            <Text style={styles.zoomedTime}>{formatDateTimeTz(currentImg.timestamp, currentImg.timezone || config.defaultTimezone)}</Text>
            {currentImg.description ? (
              <Text style={styles.zoomedDesc}>{currentImg.description}</Text>
            ) : null}
          </View>

          {/* Verdict banner */}
          {verdict && (
            <View style={[styles.verdictBanner, { backgroundColor: VERDICT_BG[verdict.v] }]}>
              <Text style={[styles.verdictText, { color: VERDICT_COLOR[verdict.v] }]}>
                {verdict.v}{verdict.msg ? ` — ${verdict.msg}` : ''}
              </Text>
            </View>
          )}

          {/* Action buttons - row 1 */}
          <TouchableOpacity
            activeOpacity={1}
            onPress={e => e.stopPropagation?.()}
            style={styles.btnRow}
          >
            <TouchableOpacity
              style={[styles.actionBtn, styles.similarBtn, showSimilar && styles.actionBtnActive]}
              onPress={handleFindSimilar}
            >
              <Text style={styles.actionBtnText}>🔍 Similar</Text>
            </TouchableOpacity>

            {dresReady && (
              <TouchableOpacity
                style={[styles.actionBtn, styles.dresBtn, submitting && styles.actionBtnDisabled]}
                onPress={handleSubmitToDRES}
                disabled={submitting}
              >
                {submitting
                  ? <ActivityIndicator size="small" color="#fff" />
                  : <Text style={styles.actionBtnText}>🏆 DRES</Text>}
              </TouchableOpacity>
            )}

            <TouchableOpacity style={[styles.actionBtn, styles.deleteBtn]} onPress={handleDelete}>
              <Text style={styles.actionBtnText}>🗑</Text>
            </TouchableOpacity>
          </TouchableOpacity>

          {/* Action buttons - row 2: save, share, info */}
          <TouchableOpacity
            activeOpacity={1}
            onPress={e => e.stopPropagation?.()}
            style={[styles.btnRow, styles.btnRowSecond]}
          >
            <TouchableOpacity
              style={[styles.actionBtn, styles.saveBtn, saving && styles.actionBtnDisabled]}
              onPress={handleSave}
              disabled={saving}
            >
              {saving
                ? <ActivityIndicator size="small" color="#fff" />
                : <Text style={styles.actionBtnText}>💾 Save</Text>}
            </TouchableOpacity>

            <TouchableOpacity
              style={[styles.actionBtn, styles.shareBtn, saving && styles.actionBtnDisabled]}
              onPress={handleShare}
              disabled={saving}
            >
              <Text style={styles.actionBtnText}>↗ Share</Text>
            </TouchableOpacity>

            <TouchableOpacity
              style={[styles.actionBtn, styles.infoBtn, showInfo && styles.actionBtnActive]}
              onPress={() => setShowInfo(v => !v)}
            >
              {loadingMeta
                ? <ActivityIndicator size="small" color="#fff" />
                : <Text style={styles.actionBtnText}>ℹ️ Info</Text>}
            </TouchableOpacity>

            <TouchableOpacity
              style={[styles.actionBtn, styles.bboxBtn, !showBBoxes && styles.actionBtnDisabled]}
              onPress={() => setShowBBoxes(v => !v)}
            >
              <Text style={styles.actionBtnText}>{showBBoxes ? '🔲' : '⬜'} Boxes</Text>
            </TouchableOpacity>
          </TouchableOpacity>

          {/* Info / metadata panel */}
          {showInfo && (
            <TouchableOpacity activeOpacity={1} onPress={e => e.stopPropagation?.()} style={styles.infoPanel}>
              <ScrollView style={styles.infoPanelScroll} nestedScrollEnabled>
                <InfoPanel metadata={metadata} />
              </ScrollView>
            </TouchableOpacity>
          )}

          {/* Similar images panel */}
          {showSimilar && (
            <TouchableOpacity activeOpacity={1} onPress={e => e.stopPropagation?.()} style={styles.similarPanel}>
              <View style={styles.similarHeader}>
                <Text style={styles.similarTitle}>Similar images</Text>
                {loadingSimilar && <ActivityIndicator size="small" color={COLORS.primary} />}
                <TouchableOpacity onPress={() => setShowSimilar(false)}>
                  <Text style={styles.similarClose}>✕</Text>
                </TouchableOpacity>
              </View>
              <FlatList
                data={similarImgs}
                keyExtractor={item => item.imagePath}
                horizontal
                showsHorizontalScrollIndicator={false}
                contentContainerStyle={styles.similarList}
                renderItem={({ item }) => {
                  const sUri = thumbUri(item, deviceId);
                  const isActive = item.imagePath === currentImg.imagePath;
                  return (
                    <TouchableOpacity
                      onPress={() => { setCurrentImg(item); setVerdict(null); setPaused(true); }}
                      style={[styles.similarThumb, isActive && styles.similarThumbActive]}
                    >
                      {sUri
                        ? <Image source={{ uri: sUri }} style={styles.similarImg} resizeMode="cover" />
                        : <View style={[styles.similarImg, styles.placeholder]} />}
                      {item.isVideo && (
                        <View style={styles.similarPlayOverlay}>
                          <Text style={styles.similarPlayIcon}>▶</Text>
                        </View>
                      )}
                      <Text style={styles.similarTime}>{formatTimeTz(item.timestamp, item.timezone || config.defaultTimezone)}</Text>
                    </TouchableOpacity>
                  );
                }}
                ListEmptyComponent={
                  !loadingSimilar ? (
                    <Text style={styles.noSimilar}>No similar images found</Text>
                  ) : null
                }
              />
            </TouchableOpacity>
          )}
        </TouchableOpacity>
      </Modal>
    </>
  );
};

const BORING_LOC_NAMES = new Set(['---', 'Unknown Place', 'Unknown', '']);

// ── Zoomed image with bounding-box overlay ────────────────────────────────────
const calcBBoxRect = (
  bbox: number[],
  containerW: number, containerH: number,
  natW: number, natH: number,
) => {
  const scale = Math.min(containerW / natW, containerH / natH);
  const dispW = natW * scale;
  const dispH = natH * scale;
  const ox = (containerW - dispW) / 2;
  const oy = (containerH - dispH) / 2;
  const [x0, y0, x1, y1] = bbox;
  return { left: ox + x0 * dispW, top: oy + y0 * dispH, width: (x1 - x0) * dispW, height: (y1 - y0) * dispH };
};

const ZoomedImageWithBBoxes = ({
  img, deviceId, authHeaders, paused, setPaused, videoRef, metadata, showBBoxes, containerStyle,
}: {
  img: ImageObject;
  deviceId: string;
  authHeaders: Record<string, string>;
  paused: boolean;
  setPaused: (fn: (p: boolean) => boolean) => void;
  videoRef: React.RefObject<VideoRef>;
  metadata: ImageMetadata | null;
  showBBoxes: boolean;
  containerStyle: object;
}) => {
  const [containerSize, setContainerSize] = useState({ width: 0, height: 0 });
  const [natSize, setNatSize] = useState({ width: 1, height: 1 });
  const uri = thumbUri(img, deviceId);

  const boxes = containerSize.width > 0 && metadata ? [
    ...(metadata.people ?? []).map((p, i) => ({ key: `p${i}`, bbox: p.bbox, label: `${p.clusterName || p.label} ${Math.round(p.confidence * 100)}%`, color: '#ff1744' })),
    ...(metadata.objects ?? []).map((o, i) => ({ key: `o${i}`, bbox: o.bbox, label: `${o.label} ${Math.round(o.confidence * 100)}%`, color: '#00e676' })),
  ].filter(b => b.bbox?.length === 4) : [];

  return (
    <View
      style={containerStyle}
      onLayout={e => setContainerSize({ width: e.nativeEvent.layout.width, height: e.nativeEvent.layout.height })}
    >
      {img.isVideo ? (
        <TouchableOpacity activeOpacity={1} onPress={() => setPaused(p => !p)} style={StyleSheet.absoluteFill}>
          <Video
            ref={videoRef}
            source={{ uri: fullUri(img, deviceId), headers: authHeaders }}
            style={StyleSheet.absoluteFill}
            resizeMode="contain"
            paused={paused}
            repeat
            onError={() => Alert.alert('Error', 'Could not load video.')}
          />
          {paused && (
            <View style={styles.videoPauseOverlay}>
              <Text style={styles.videoPauseIcon}>▶</Text>
            </View>
          )}
        </TouchableOpacity>
      ) : uri ? (
        <Image
          source={{ uri }}
          style={StyleSheet.absoluteFill}
          resizeMode="contain"
          onLoad={e => setNatSize({ width: e.nativeEvent.source.width, height: e.nativeEvent.source.height })}
        />
      ) : null}

      {showBBoxes && boxes.map(b => {
        const r = calcBBoxRect(b.bbox, containerSize.width, containerSize.height, natSize.width, natSize.height);
        return (
          <View key={b.key} style={[bboxSt.box, { left: r.left, top: r.top, width: r.width, height: r.height, borderColor: b.color }]}>
            <Text style={[bboxSt.label, { backgroundColor: b.color }]} numberOfLines={1}>{b.label}</Text>
          </View>
        );
      })}
    </View>
  );
};

const bboxSt = StyleSheet.create({
  box: { position: 'absolute', borderWidth: 2, borderRadius: 2 },
  label: { position: 'absolute', top: -17, left: -1, color: '#fff', fontSize: 9, fontWeight: '700', paddingHorizontal: 4, paddingVertical: 2, borderRadius: 3, overflow: 'hidden' },
});

const buildMapHtml = (lat: number, lng: number) => `
<!DOCTYPE html><html><head>
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>*{margin:0;padding:0;}html,body,#map{width:100%;height:100%;}</style>
</head><body><div id="map"></div><script>
var map=L.map('map',{zoomControl:false,attributionControl:false}).setView([${lat},${lng}],15);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);
L.marker([${lat},${lng}]).addTo(map);
</script></body></html>`;

const InfoPanel = ({ metadata }: { metadata: ImageMetadata | null }) => {
  if (!metadata) {
    return <Text style={ip.empty}>Loading details…</Text>;
  }

  const loc = metadata.location;
  const locName = loc?.name && !BORING_LOC_NAMES.has(loc.name) ? loc.name : null;
  const locParts = [locName, loc?.address].filter(Boolean).join(', ');
  const locLine = [locParts, loc?.country].filter(Boolean).join(' · ');
  const hasGps = metadata.gps && typeof metadata.gps.latitude === 'number';

  return (
    <View style={ip.container}>
      {(locLine || hasGps) ? (
        <View style={ip.section}>
          <Text style={ip.sectionTitle}>📍 Location</Text>
          {locLine ? <Text style={ip.locText}>{locLine}</Text> : null}
          {hasGps ? (
            <Text style={ip.coords}>{metadata.gps!.latitude.toFixed(5)}, {metadata.gps!.longitude.toFixed(5)}</Text>
          ) : null}
          {hasGps && (
            <WebView
              source={{ html: buildMapHtml(metadata.gps!.latitude, metadata.gps!.longitude) }}
              style={ip.map}
              scrollEnabled={false}
              javaScriptEnabled
            />
          )}
        </View>
      ) : null}

      {metadata.people.length > 0 && (
        <View style={ip.section}>
          <Text style={ip.sectionTitle}>👤 People ({metadata.people.length})</Text>
          <View style={ip.chips}>
            {metadata.people.map((p, i) => (
              <View key={i} style={[ip.chip, ip.chipPerson]}>
                <Text style={ip.chipText}>{p.clusterName || p.label} {Math.round(p.confidence * 100)}%</Text>
              </View>
            ))}
          </View>
        </View>
      )}

      {metadata.objects.length > 0 && (
        <View style={ip.section}>
          <Text style={ip.sectionTitle}>📦 Objects ({metadata.objects.length})</Text>
          <View style={ip.chips}>
            {metadata.objects.map((o, i) => (
              <View key={i} style={[ip.chip, ip.chipObject]}>
                <Text style={ip.chipText}>{o.label} {Math.round(o.confidence * 100)}%</Text>
              </View>
            ))}
          </View>
        </View>
      )}

      {!locLine && !hasGps && metadata.people.length === 0 && metadata.objects.length === 0 && (
        <Text style={ip.empty}>No additional metadata available</Text>
      )}
    </View>
  );
};

const ip = StyleSheet.create({
  container: { padding: 12 },
  section: { marginBottom: 14 },
  sectionTitle: { color: COLORS.primary, fontWeight: '700', fontSize: 12, marginBottom: 6, textTransform: 'uppercase', letterSpacing: 0.5 },
  locText: { color: '#fff', fontSize: 13, marginBottom: 2 },
  coords: { color: 'rgba(255,255,255,0.5)', fontSize: 11, marginBottom: 8 },
  map: { height: 150, borderRadius: 8, overflow: 'hidden' },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  chip: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 14 },
  chipPerson: { backgroundColor: 'rgba(255,23,68,0.25)', borderWidth: 1, borderColor: '#ff1744' },
  chipObject: { backgroundColor: 'rgba(0,230,118,0.15)', borderWidth: 1, borderColor: '#00e676' },
  chipText: { color: '#fff', fontSize: 11, fontWeight: '600' },
  empty: { color: 'rgba(255,255,255,0.4)', fontSize: 13, padding: 12, textAlign: 'center' },
});

const styles = StyleSheet.create({
  card: { borderRadius: 8, overflow: 'hidden', margin: 2, backgroundColor: COLORS.divider },
  image: { width: '100%', height: '100%' },
  placeholder: { alignItems: 'center', justifyContent: 'center', backgroundColor: '#e0e0e0' },
  placeholderText: { fontSize: 11, color: COLORS.textSecondary },
  playOverlay: {
    position: 'absolute', top: 0, left: 0, right: 0, bottom: 0,
    alignItems: 'center', justifyContent: 'center',
    backgroundColor: 'rgba(0,0,0,0.25)',
  },
  playIcon: { fontSize: 22, color: '#fff' },
  badge: {
    position: 'absolute', bottom: 0, left: 0, right: 0,
    backgroundColor: 'rgba(0,0,0,0.45)', paddingHorizontal: 4, paddingVertical: 2,
  },
  badgeText: { color: '#fff', fontSize: 9 },

  overlay: {
    flex: 1, backgroundColor: 'rgba(0,0,0,0.92)',
    alignItems: 'center', justifyContent: 'center',
  },
  zoomedImage: { width: '100%', height: '55%', overflow: 'hidden' },
  zoomedImageSmall: { width: '100%', height: '36%', overflow: 'hidden' },
  videoPauseOverlay: {
    ...StyleSheet.absoluteFill,
    alignItems: 'center', justifyContent: 'center',
    backgroundColor: 'rgba(0,0,0,0.3)',
  },
  videoPauseIcon: { fontSize: 44, color: 'rgba(255,255,255,0.85)' },

  zoomedMeta: { padding: 8, alignItems: 'center' },
  zoomedTime: { color: '#fff', fontSize: 13, fontWeight: '600' },
  zoomedDesc: {
    color: 'rgba(255,255,255,0.7)', fontSize: 12, marginTop: 3,
    textAlign: 'center', paddingHorizontal: 16,
  },
  verdictBanner: {
    marginTop: 4, paddingHorizontal: 20, paddingVertical: 6,
    borderRadius: 10, marginHorizontal: 24,
  },
  verdictText: { fontSize: 13, fontWeight: '700', textAlign: 'center' },

  btnRow: {
    flexDirection: 'row', gap: 8, marginTop: 8, paddingHorizontal: 20,
  },
  btnRowSecond: { marginTop: 6 },
  actionBtn: {
    flex: 1, paddingVertical: 10, borderRadius: 22, alignItems: 'center',
  },
  actionBtnActive: { opacity: 0.7 },
  actionBtnDisabled: { opacity: 0.5 },
  actionBtnText: { color: '#fff', fontWeight: '700', fontSize: 12 },
  similarBtn: { backgroundColor: COLORS.primary },
  dresBtn: { backgroundColor: COLORS.secondary },
  deleteBtn: { backgroundColor: '#c0392b', flex: 0, paddingHorizontal: 14 },
  saveBtn: { backgroundColor: '#5d6d7e' },
  shareBtn: { backgroundColor: '#2980b9' },
  infoBtn: { backgroundColor: '#6c3483', flex: 0, paddingHorizontal: 14 },
  bboxBtn: { backgroundColor: '#1a5276', flex: 0, paddingHorizontal: 14 },
  infoPanel: {
    position: 'absolute', bottom: 0, left: 0, right: 0,
    backgroundColor: 'rgba(20,20,20,0.97)',
    borderTopLeftRadius: 18, borderTopRightRadius: 18,
    maxHeight: '50%',
  },
  infoPanelScroll: { flex: 1 },

  // Similar panel
  similarPanel: {
    position: 'absolute', bottom: 0, left: 0, right: 0,
    backgroundColor: 'rgba(20,20,20,0.97)',
    borderTopLeftRadius: 18, borderTopRightRadius: 18,
    paddingBottom: 12,
  },
  similarHeader: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingHorizontal: 16, paddingVertical: 10,
  },
  similarTitle: { color: '#fff', fontWeight: '700', fontSize: 14, flex: 1 },
  similarClose: { color: 'rgba(255,255,255,0.6)', fontSize: 18, paddingLeft: 12 },
  similarList: { paddingHorizontal: 10, gap: 6 },
  similarThumb: {
    width: 90, borderRadius: 8, overflow: 'hidden',
    borderWidth: 2, borderColor: 'transparent',
  },
  similarThumbActive: { borderColor: COLORS.primary },
  similarImg: { width: 90, height: 90 },
  similarPlayOverlay: {
    position: 'absolute', top: 0, left: 0, right: 0, bottom: 18,
    alignItems: 'center', justifyContent: 'center',
    backgroundColor: 'rgba(0,0,0,0.2)',
  },
  similarPlayIcon: { fontSize: 16, color: '#fff' },
  similarTime: { color: '#ccc', fontSize: 9, textAlign: 'center', paddingTop: 2 },
  noSimilar: { color: 'rgba(255,255,255,0.5)', fontSize: 13, padding: 20 },
});

export default ImageCard;
