import React, { useCallback, useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  FlatList,
  Image,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { forceDeleteImage, getDeletedImages, restoreImage } from '../api/browsing';
import { useAppSelector } from '../store';
import { COLORS } from '../constants';
import { ImageObject } from '../types';
import dayjs from 'dayjs';

const DeletedImagesScreen = () => {
  const deviceId = useAppSelector(s => s.auth.deviceId);
  const [images, setImages] = useState<ImageObject[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null); // path of image being acted on

  const load = useCallback(() => {
    if (!deviceId) { return; }
    setLoading(true);
    getDeletedImages(deviceId)
      .then(res => setImages(res.data))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [deviceId]);

  useEffect(() => { load(); }, [load]);

  const handleRestore = (img: ImageObject) => {
    if (!deviceId) { return; }
    Alert.alert('Restore image?', img.imagePath.split('/').pop(), [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Restore', onPress: async () => {
          setBusy(img.imagePath);
          try {
            await restoreImage(deviceId, img.imagePath);
            setImages(prev => prev.filter(i => i.imagePath !== img.imagePath));
          } catch {
            Alert.alert('Error', 'Could not restore image.');
          } finally { setBusy(null); }
        },
      },
    ]);
  };

  const handleForceDelete = (img: ImageObject) => {
    if (!deviceId) { return; }
    Alert.alert(
      'Permanently delete?',
      'This cannot be undone.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Delete forever', style: 'destructive', onPress: async () => {
            setBusy(img.imagePath);
            try {
              await forceDeleteImage(deviceId, img.imagePath);
              setImages(prev => prev.filter(i => i.imagePath !== img.imagePath));
            } catch {
              Alert.alert('Error', 'Could not permanently delete image.');
            } finally { setBusy(null); }
          },
        },
      ],
    );
  };

  const handleRestoreAll = () => {
    if (!deviceId || images.length === 0) { return; }
    Alert.alert(
      'Restore all?',
      `Restore all ${images.length} deleted images?`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Restore all', onPress: async () => {
            setLoading(true);
            for (const img of images) {
              await restoreImage(deviceId, img.imagePath).catch(() => {});
            }
            setImages([]);
            setLoading(false);
          },
        },
      ],
    );
  };

  if (loading) {
    return <ActivityIndicator style={{ flex: 1 }} color={COLORS.primary} size="large" />;
  }

  return (
    <View style={styles.container}>
      {/* Header */}
      <View style={styles.header}>
        <Text style={styles.title}>Deleted Images</Text>
        <Text style={styles.count}>{images.length} item{images.length !== 1 ? 's' : ''}</Text>
        {images.length > 0 && (
          <TouchableOpacity style={styles.restoreAllBtn} onPress={handleRestoreAll}>
            <Text style={styles.restoreAllText}>Restore all</Text>
          </TouchableOpacity>
        )}
      </View>

      {images.length === 0 ? (
        <View style={styles.empty}>
          <Text style={styles.emptyIcon}>🗑</Text>
          <Text style={styles.emptyText}>No deleted images</Text>
          <Text style={styles.emptyHint}>Soft-deleted images appear here for 7 days.</Text>
        </View>
      ) : (
        <FlatList
          data={images}
          keyExtractor={i => i.imagePath}
          contentContainerStyle={styles.list}
          renderItem={({ item }) => {
            const isBusy = busy === item.imagePath;
            return (
              <View style={styles.row}>
                <Image source={{ uri: item.thumbnail ?? item.imagePath }} style={styles.thumb} />
                <View style={styles.rowInfo}>
                  <Text style={styles.rowPath} numberOfLines={1}>{item.imagePath.split('/').pop()}</Text>
                  <Text style={styles.rowDate}>{dayjs(item.timestamp).format('D MMM YYYY, HH:mm')}</Text>
                </View>
                {isBusy ? (
                  <ActivityIndicator size="small" color={COLORS.primary} style={styles.rowSpinner} />
                ) : (
                  <View style={styles.rowBtns}>
                    <TouchableOpacity style={styles.restoreBtn} onPress={() => handleRestore(item)}>
                      <Text style={styles.restoreBtnText}>Restore</Text>
                    </TouchableOpacity>
                    <TouchableOpacity style={styles.deleteBtn} onPress={() => handleForceDelete(item)}>
                      <Text style={styles.deleteBtnText}>Delete</Text>
                    </TouchableOpacity>
                  </View>
                )}
              </View>
            );
          }}
        />
      )}
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.background },
  header: {
    flexDirection: 'row', alignItems: 'center', padding: 16,
    borderBottomWidth: 1, borderColor: COLORS.divider, gap: 8, flexWrap: 'wrap',
  },
  title: { fontSize: 18, fontWeight: '700', color: COLORS.purple, flex: 1 },
  count: { fontSize: 13, color: COLORS.textSecondary },
  restoreAllBtn: {
    paddingHorizontal: 12, paddingVertical: 6, borderRadius: 8,
    backgroundColor: COLORS.secondary,
  },
  restoreAllText: { color: '#fff', fontWeight: '600', fontSize: 13 },

  list: { padding: 12, gap: 10 },
  row: {
    flexDirection: 'row', alignItems: 'center', backgroundColor: COLORS.surface,
    borderRadius: 12, overflow: 'hidden', elevation: 1,
  },
  thumb: { width: 72, height: 72 },
  rowInfo: { flex: 1, padding: 10, gap: 4 },
  rowPath: { fontSize: 13, fontWeight: '600', color: COLORS.textPrimary },
  rowDate: { fontSize: 11, color: COLORS.textSecondary },
  rowSpinner: { padding: 16 },
  rowBtns: { padding: 10, gap: 6 },
  restoreBtn: {
    paddingHorizontal: 10, paddingVertical: 5, borderRadius: 6,
    backgroundColor: COLORS.secondary, alignItems: 'center',
  },
  restoreBtnText: { color: '#fff', fontWeight: '600', fontSize: 12 },
  deleteBtn: {
    paddingHorizontal: 10, paddingVertical: 5, borderRadius: 6,
    borderWidth: 1, borderColor: COLORS.primary, alignItems: 'center',
  },
  deleteBtnText: { color: COLORS.primary, fontWeight: '600', fontSize: 12 },

  empty: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 8 },
  emptyIcon: { fontSize: 48 },
  emptyText: { fontSize: 16, fontWeight: '600', color: COLORS.textPrimary },
  emptyHint: { fontSize: 13, color: COLORS.textSecondary, textAlign: 'center', paddingHorizontal: 40 },
});

export default DeletedImagesScreen;
