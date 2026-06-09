import React, { useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import dayjs from 'dayjs';
import { deleteImages, getAllDates, getImagesByHour } from '../api/browsing';
import { useAppSelector } from '../store';
import { COLORS } from '../constants';

const DeleteRangeScreen = () => {
  const deviceId = useAppSelector(s => s.auth.deviceId);
  const [dates, setDates] = useState<string[]>([]);
  const [loadingDates, setLoadingDates] = useState(true);
  const [selectedDates, setSelectedDates] = useState<Set<string>>(new Set());
  const [deleting, setDeleting] = useState(false);
  const [deleteProgress, setDeleteProgress] = useState('');

  useEffect(() => {
    if (!deviceId) { return; }
    getAllDates(deviceId)
      .then(res => setDates(res.data as string[]))
      .catch(() => {})
      .finally(() => setLoadingDates(false));
  }, [deviceId]);

  const toggle = (date: string) => {
    setSelectedDates(prev => {
      const next = new Set(prev);
      if (next.has(date)) { next.delete(date); } else { next.add(date); }
      return next;
    });
  };

  const selectAll = () => setSelectedDates(new Set(dates));
  const clearAll = () => setSelectedDates(new Set());

  const collectImagePaths = async (date: string): Promise<string[]> => {
    const paths: string[] = [];
    // Fetch first page to get available_hours
    const first = await getImagesByHour(deviceId!, date, 0, 1);
    const { available_hours = [] } = first.data as any;

    for (const hour of available_hours) {
      let page = 1;
      let totalPages = 1;
      do {
        const res = await getImagesByHour(deviceId!, date, hour, page);
        const { images = [], total_pages = 1 } = res.data as any;
        for (const img of images) { paths.push(img.imagePath); }
        totalPages = total_pages;
        page++;
      } while (page <= totalPages);
    }
    return paths;
  };

  const handleDelete = () => {
    if (selectedDates.size === 0 || !deviceId) { return; }
    const dateList = Array.from(selectedDates).sort();
    Alert.alert(
      `Delete ${selectedDates.size} date${selectedDates.size > 1 ? 's' : ''}?`,
      `All images for the selected dates will be soft-deleted. You can restore them from Deleted Images within 7 days.`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Delete', style: 'destructive', onPress: async () => {
            setDeleting(true);
            let total = 0;
            for (let idx = 0; idx < dateList.length; idx++) {
              const date = dateList[idx];
              setDeleteProgress(`Collecting ${dayjs(date).format('D MMM')} (${idx + 1}/${dateList.length})…`);
              try {
                const paths = await collectImagePaths(date);
                if (paths.length > 0) {
                  await deleteImages(deviceId, paths);
                  total += paths.length;
                }
              } catch { /* skip on error */ }
            }
            setDeleting(false);
            setDeleteProgress('');
            setSelectedDates(new Set());
            Alert.alert('Done', `${total} image${total !== 1 ? 's' : ''} soft-deleted.`);
          },
        },
      ],
    );
  };

  if (loadingDates) {
    return <ActivityIndicator style={{ flex: 1 }} color={COLORS.primary} size="large" />;
  }

  return (
    <View style={styles.container}>
      {/* Toolbar */}
      <View style={styles.toolbar}>
        <Text style={styles.toolbarTitle}>
          {selectedDates.size > 0 ? `${selectedDates.size} selected` : 'Select dates to delete'}
        </Text>
        <TouchableOpacity onPress={selectedDates.size === dates.length ? clearAll : selectAll}>
          <Text style={styles.toolbarAction}>
            {selectedDates.size === dates.length ? 'Deselect all' : 'Select all'}
          </Text>
        </TouchableOpacity>
      </View>

      {/* Date chips */}
      <ScrollView contentContainerStyle={styles.chips}>
        {dates.map(d => {
          const on = selectedDates.has(d);
          return (
            <TouchableOpacity
              key={d}
              style={[styles.chip, on && styles.chipSelected]}
              onPress={() => toggle(d)}
              disabled={deleting}
            >
              <Text style={[styles.chipText, on && styles.chipTextSelected]}>
                {dayjs(d).format('D MMM YYYY')}
              </Text>
            </TouchableOpacity>
          );
        })}
      </ScrollView>

      {/* Footer */}
      <View style={styles.footer}>
        {deleting ? (
          <View style={styles.deleteProgress}>
            <ActivityIndicator color={COLORS.primary} />
            <Text style={styles.deleteProgressText}>{deleteProgress}</Text>
          </View>
        ) : (
          <TouchableOpacity
            style={[styles.deleteBtn, selectedDates.size === 0 && styles.deleteBtnDisabled]}
            onPress={handleDelete}
            disabled={selectedDates.size === 0}
          >
            <Text style={styles.deleteBtnText}>
              Soft-delete {selectedDates.size > 0 ? `${selectedDates.size} date${selectedDates.size > 1 ? 's' : ''}` : 'selected dates'}
            </Text>
          </TouchableOpacity>
        )}
        <Text style={styles.footerHint}>
          Images can be restored from Deleted Images within 7 days.
        </Text>
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.background },
  toolbar: {
    flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center',
    paddingHorizontal: 16, paddingVertical: 12,
    borderBottomWidth: 1, borderColor: COLORS.divider, backgroundColor: COLORS.surface,
  },
  toolbarTitle: { fontSize: 14, fontWeight: '600', color: COLORS.textPrimary },
  toolbarAction: { fontSize: 13, color: COLORS.primary, fontWeight: '600' },

  chips: { flexDirection: 'row', flexWrap: 'wrap', padding: 12, gap: 8 },
  chip: {
    paddingHorizontal: 14, paddingVertical: 7, borderRadius: 20,
    borderWidth: 1, borderColor: COLORS.divider, backgroundColor: COLORS.surface,
  },
  chipSelected: { backgroundColor: COLORS.primary, borderColor: COLORS.primary },
  chipText: { fontSize: 13, color: COLORS.textPrimary },
  chipTextSelected: { color: '#fff', fontWeight: '600' },

  footer: {
    padding: 16, borderTopWidth: 1, borderColor: COLORS.divider,
    backgroundColor: COLORS.surface, gap: 8,
  },
  deleteBtn: {
    backgroundColor: COLORS.primary, borderRadius: 12,
    paddingVertical: 14, alignItems: 'center',
  },
  deleteBtnDisabled: { opacity: 0.4 },
  deleteBtnText: { color: '#fff', fontWeight: '700', fontSize: 15 },
  deleteProgress: { flexDirection: 'row', alignItems: 'center', gap: 10, justifyContent: 'center', paddingVertical: 8 },
  deleteProgressText: { fontSize: 13, color: COLORS.textSecondary },
  footerHint: { fontSize: 11, color: COLORS.textSecondary, textAlign: 'center' },
});

export default DeleteRangeScreen;
