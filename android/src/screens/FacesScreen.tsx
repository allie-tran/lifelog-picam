import React, { useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  FlatList,
  Image,
  Modal,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { useNavigation } from '@react-navigation/native';
import type { BottomTabNavigationProp } from '@react-navigation/bottom-tabs';
import { getAllFaces } from '../api/browsing';
import { addFaceToWhitelist, removeFaceFromWhitelist } from '../api/face';
import { useAppDispatch, useAppSelector } from '../store';
import { setSearchQuery } from '../store/slices/searchSlice';
import { COLORS } from '../constants';
import type { MainTabParamList } from '../types';

interface Face {
  id: string;
  name: string;
  images: string[];
}

const FacesScreen = () => {
  const deviceId = useAppSelector(s => s.auth.deviceId);
  const dispatch = useAppDispatch();
  const navigation = useNavigation<BottomTabNavigationProp<MainTabParamList>>();
  const [faces, setFaces] = useState<Face[]>([]);
  const [loading, setLoading] = useState(true);

  // Rename modal state
  const [renameTarget, setRenameTarget] = useState<Face | null>(null);
  const [newName, setNewName] = useState('');
  const [saving, setSaving] = useState(false);

  const load = () => {
    if (!deviceId) { return; }
    setLoading(true);
    getAllFaces(deviceId)
      .then(res => setFaces(res.data))
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, [deviceId]);

  const openRename = (face: Face) => {
    setRenameTarget(face);
    setNewName(face.name);
  };

  const handleRename = async () => {
    if (!renameTarget || !newName.trim() || !deviceId) { return; }
    const trimmed = newName.trim();
    setSaving(true);
    try {
      // Add under the new name using existing cluster images as training data
      await addFaceToWhitelist(deviceId, trimmed, renameTarget.images);
      // Remove old entry if name actually changed
      if (trimmed !== renameTarget.name) {
        await removeFaceFromWhitelist(deviceId, renameTarget.name).catch(() => {});
      }
      setRenameTarget(null);
      load();
    } catch {
      Alert.alert('Error', 'Failed to rename. Try again.');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <ActivityIndicator style={{ flex: 1 }} color={COLORS.primary} size="large" />;
  }

  return (
    <>
      <View style={styles.container}>
        <Text style={styles.header}>People</Text>
        <FlatList
          data={faces}
          keyExtractor={f => f.id}
          numColumns={3}
          contentContainerStyle={styles.grid}
          renderItem={({ item }) => (
            <TouchableOpacity
              style={styles.card}
              onPress={() => {
                dispatch(setSearchQuery({ peopleIds: [item.id] }));
                navigation.navigate('Search');
              }}
              onLongPress={() => openRename(item)}
              delayLongPress={400}
            >
              {item.images[0] ? (
                <Image source={{ uri: item.images[0] }} style={styles.avatar} resizeMode="cover" />
              ) : (
                <View style={[styles.avatar, styles.avatarPlaceholder]}>
                  <Text style={styles.avatarInitial}>{item.name.charAt(0).toUpperCase()}</Text>
                </View>
              )}
              <Text style={styles.name} numberOfLines={1}>{item.name}</Text>
              <Text style={styles.hint}>hold to rename</Text>
            </TouchableOpacity>
          )}
          ListEmptyComponent={
            <View style={styles.empty}>
              <Text style={styles.emptyText}>No people found</Text>
            </View>
          }
        />
      </View>

      {/* Rename modal */}
      <Modal
        visible={!!renameTarget}
        transparent
        animationType="slide"
        onRequestClose={() => setRenameTarget(null)}
      >
        <View style={styles.modalOverlay}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Rename Person</Text>

            {/* Face preview */}
            {renameTarget?.images[0] ? (
              <Image
                source={{ uri: renameTarget.images[0] }}
                style={styles.modalAvatar}
                resizeMode="cover"
              />
            ) : null}

            <TextInput
              style={styles.input}
              value={newName}
              onChangeText={setNewName}
              placeholder="Enter name…"
              placeholderTextColor={COLORS.textSecondary}
              autoFocus
              returnKeyType="done"
              onSubmitEditing={handleRename}
            />

            <View style={styles.modalBtns}>
              <TouchableOpacity style={styles.cancelBtn} onPress={() => setRenameTarget(null)}>
                <Text style={styles.cancelBtnText}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.saveBtn, (!newName.trim() || saving) && styles.saveBtnDisabled]}
                onPress={handleRename}
                disabled={!newName.trim() || saving}
              >
                {saving
                  ? <ActivityIndicator size="small" color="#fff" />
                  : <Text style={styles.saveBtnText}>Save</Text>}
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    </>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.background },
  header: { fontSize: 20, fontWeight: '700', color: COLORS.purple, padding: 16 },
  grid: { paddingHorizontal: 8, paddingBottom: 24 },
  card: { flex: 1 / 3, alignItems: 'center', padding: 8 },
  avatar: { width: 80, height: 80, borderRadius: 40, borderWidth: 2, borderColor: COLORS.primary },
  avatarPlaceholder: { backgroundColor: COLORS.divider, alignItems: 'center', justifyContent: 'center' },
  avatarInitial: { fontSize: 28, fontWeight: '700', color: COLORS.textSecondary },
  name: { marginTop: 6, fontSize: 12, color: COLORS.textPrimary, textAlign: 'center', maxWidth: 90 },
  hint: { fontSize: 9, color: COLORS.textSecondary, marginTop: 2 },
  empty: { padding: 40, alignItems: 'center' },
  emptyText: { color: COLORS.textSecondary, fontSize: 14 },
  // Modal
  modalOverlay: { flex: 1, backgroundColor: 'rgba(0,0,0,0.5)', justifyContent: 'flex-end' },
  modalCard: {
    backgroundColor: COLORS.surface, borderTopLeftRadius: 20, borderTopRightRadius: 20,
    padding: 20, paddingBottom: 34, alignItems: 'center', gap: 12,
  },
  modalTitle: { fontSize: 16, fontWeight: '700', color: COLORS.textPrimary },
  modalAvatar: { width: 80, height: 80, borderRadius: 40 },
  input: {
    width: '100%', borderWidth: 1, borderColor: COLORS.divider, borderRadius: 10,
    paddingHorizontal: 14, paddingVertical: 10, fontSize: 15, color: COLORS.textPrimary,
  },
  modalBtns: { flexDirection: 'row', gap: 10, width: '100%' },
  cancelBtn: {
    flex: 1, paddingVertical: 12, borderRadius: 10,
    borderWidth: 1, borderColor: COLORS.divider, alignItems: 'center',
  },
  cancelBtnText: { fontSize: 14, color: COLORS.textSecondary, fontWeight: '600' },
  saveBtn: { flex: 1, paddingVertical: 12, borderRadius: 10, backgroundColor: COLORS.secondary, alignItems: 'center' },
  saveBtnDisabled: { opacity: 0.45 },
  saveBtnText: { color: '#fff', fontWeight: '700', fontSize: 14 },
});

export default FacesScreen;
