import React, { useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  FlatList,
  Image,
  Modal,
  PermissionsAndroid,
  Platform,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import Video, { VideoRef } from 'react-native-video';
import { CameraRoll } from '@react-native-camera-roll/camera-roll';
import RNShare from 'react-native-share';
import RNFS from 'react-native-fs';
import { config, COLORS } from '../constants';
import { ImageObject } from '../types';
import { useAppDispatch, useAppSelector } from '../store';
import { addSubmission } from '../store/slices/dresSlice';
import { submitImageToDRES, SubmitVerdict } from '../api/dres';
import { deleteImage, similarImages } from '../api/browsing';
import dayjs from 'dayjs';
import utc from 'dayjs/plugin/utc';
import timezone from 'dayjs/plugin/timezone';

dayjs.extend(utc);
dayjs.extend(timezone);

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

const thumbUri = (img: ImageObject, deviceId: string) =>
  img.thumbnail ? `${config.backendUrl}/thumbnails/${deviceId}/${img.thumbnail}` : null;

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

  if (deleted) { return null; }

  const uri = thumbUri(image, deviceId);
  const ts = dayjs.utc(currentImg.timestamp).tz(currentImg.timezone ?? 'UTC');
  const authHeaders: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {};

  const handleClose = () => {
    setZoomed(false);
    setVerdict(null);
    setShowSimilar(false);
    setSimilarImgs([]);
    setCurrentImg(image);
    setPaused(true);
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
            <Text style={styles.placeholderText}>{dayjs.utc(image.timestamp).format('HH:mm')}</Text>
          </View>
        )}
        {/* Video play indicator */}
        {image.isVideo && (
          <View style={styles.playOverlay}>
            <Text style={styles.playIcon}>▶</Text>
          </View>
        )}
        <View style={styles.badge}>
          <Text style={styles.badgeText}>{dayjs.utc(image.timestamp).format('HH:mm')}</Text>
        </View>
      </TouchableOpacity>

      <Modal visible={zoomed} transparent animationType="fade" onRequestClose={handleClose}>
        <TouchableOpacity style={styles.overlay} activeOpacity={1} onPress={handleClose}>

          {/* Video or image */}
          {currentImg.isVideo ? (
            <TouchableOpacity
              activeOpacity={1}
              onPress={() => setPaused(p => !p)}
              style={showSimilar ? styles.zoomedImageSmall : styles.zoomedImage}
            >
              <Video
                ref={videoRef}
                source={{ uri: fullUri(currentImg, deviceId), headers: authHeaders }}
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
          ) : (
            thumbUri(currentImg, deviceId) ? (
              <Image
                source={{ uri: thumbUri(currentImg, deviceId)! }}
                style={showSimilar ? styles.zoomedImageSmall : styles.zoomedImage}
                resizeMode="contain"
              />
            ) : null
          )}

          {/* Meta */}
          <View style={styles.zoomedMeta}>
            <Text style={styles.zoomedTime}>{ts.format('HH:mm · D MMM YYYY')}</Text>
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

          {/* Action buttons - row 2: save & share */}
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
          </TouchableOpacity>

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
                  const sTs = dayjs.utc(item.timestamp).tz(item.timezone ?? 'UTC');
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
                      <Text style={styles.similarTime}>{sTs.format('HH:mm')}</Text>
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
  zoomedImage: { width: '100%', height: '55%' },
  zoomedImageSmall: { width: '100%', height: '36%' },
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
