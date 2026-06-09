import React, { useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import DocumentPicker, { types } from 'react-native-document-picker';
import RNFS from 'react-native-fs';
import { completeUpload, getProcessingStatus, initUpload, uploadChunk } from '../api/upload';
import { useAppSelector } from '../store';
import { COLORS } from '../constants';

const CHUNK_SIZE = 2 * 1024 * 1024; // 2 MB
const DEFAULT_DATE_FORMAT = '%Y%m%d_%H%M%S';

const UploadScreen = () => {
  const deviceId = useAppSelector(s => s.auth.deviceId);

  const [fileName, setFileName] = useState<string | null>(null);
  const [fileSize, setFileSize] = useState<number>(0);
  const [fileUri, setFileUri] = useState<string | null>(null);
  const [dateFormat, setDateFormat] = useState(DEFAULT_DATE_FORMAT);

  const [phase, setPhase] = useState<'idle' | 'copying' | 'uploading' | 'processing' | 'done' | 'error'>('idle');
  const [uploadProgress, setUploadProgress] = useState(0);   // 0–1
  const [processProgress, setProcessProgress] = useState(0); // 0–1
  const [statusMsg, setStatusMsg] = useState('');

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const abortRef = useRef(false);

  const pickFile = async () => {
    try {
      const result = await DocumentPicker.pickSingle({ type: [types.zip] });
      setFileName(result.name ?? 'upload.zip');
      setFileSize(result.size ?? 0);
      setFileUri(result.uri);
      setPhase('idle');
      setUploadProgress(0);
      setProcessProgress(0);
      setStatusMsg('');
    } catch (e) {
      if (!DocumentPicker.isCancel(e)) {
        Alert.alert('Error', 'Could not open file.');
      }
    }
  };

  const startUpload = async () => {
    if (!fileUri || !deviceId) { return; }
    abortRef.current = false;

    let tmpPath: string | null = null;
    try {
      // Copy content:// URI to a real temp file so RNFS can seek into it
      setPhase('copying');
      setStatusMsg('Copying file…');
      tmpPath = `${RNFS.TemporaryDirectoryPath}/${Date.now()}_upload.zip`;
      await RNFS.copyFile(fileUri, tmpPath);
      const stat = await RNFS.stat(tmpPath);
      const totalBytes = stat.size;
      const totalChunks = Math.ceil(totalBytes / CHUNK_SIZE);

      // Init
      setPhase('uploading');
      setStatusMsg('Initialising upload…');
      const initRes = await initUpload(deviceId, dateFormat);
      const { uploadId } = initRes.data;

      // Upload chunks
      for (let i = 0; i < totalChunks; i++) {
        if (abortRef.current) { throw new Error('Cancelled'); }
        const offset = i * CHUNK_SIZE;
        const length = Math.min(CHUNK_SIZE, totalBytes - offset);

        setStatusMsg(`Uploading chunk ${i + 1} / ${totalChunks}…`);

        // Read chunk as base64 then write it to its own temp file so FormData
        // can send it as a real binary blob.
        const b64 = await RNFS.read(tmpPath, length, offset, 'base64');
        const chunkPath = `${RNFS.TemporaryDirectoryPath}/chunk_${i}_${Date.now()}`;
        await RNFS.write(chunkPath, b64, 0, 'base64');

        const chunkUri = Platform.OS === 'android' ? `file://${chunkPath}` : chunkPath;
        await uploadChunk(uploadId, i, totalChunks, chunkUri);
        await RNFS.unlink(chunkPath).catch(() => {});

        setUploadProgress((i + 1) / totalChunks);
      }

      // Complete
      setStatusMsg('Finalising…');
      const completeRes = await completeUpload(uploadId);
      const id = completeRes.data.jobId;

      // Poll processing status
      setPhase('processing');
      setStatusMsg('Processing…');
      pollRef.current = setInterval(async () => {
        try {
          const res = await getProcessingStatus(id);
          const { status, progress, message } = res.data;
          setProcessProgress(progress ?? 0);
          if (message) { setStatusMsg(message); }
          if (status === 'done') {
            clearInterval(pollRef.current!);
            setPhase('done');
            setStatusMsg('Upload complete!');
          } else if (status === 'error') {
            clearInterval(pollRef.current!);
            setPhase('error');
            setStatusMsg(message ?? 'Processing failed.');
          }
        } catch {
          clearInterval(pollRef.current!);
          setPhase('error');
          setStatusMsg('Failed to get processing status.');
        }
      }, 3000);
    } catch (err: any) {
      if (err?.message !== 'Cancelled') {
        Alert.alert('Upload failed', err?.message ?? 'Unknown error.');
      }
      setPhase('error');
      setStatusMsg(err?.message ?? 'Upload failed.');
    } finally {
      if (tmpPath) { RNFS.unlink(tmpPath).catch(() => {}); }
    }
  };

  const cancel = () => {
    abortRef.current = true;
    if (pollRef.current) { clearInterval(pollRef.current); }
    setPhase('idle');
    setStatusMsg('');
    setUploadProgress(0);
    setProcessProgress(0);
  };

  const reset = () => {
    setFileName(null);
    setFileUri(null);
    setFileSize(0);
    setPhase('idle');
    setStatusMsg('');
    setUploadProgress(0);
    setProcessProgress(0);
  };

  const isActive = phase === 'copying' || phase === 'uploading' || phase === 'processing';
  const isDone = phase === 'done';
  const isError = phase === 'error';

  const totalProgress =
    phase === 'processing' || isDone
      ? 0.5 + processProgress * 0.5
      : uploadProgress * 0.5;

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Text style={styles.title}>Upload Images</Text>

      {/* File picker */}
      <TouchableOpacity
        style={[styles.picker, fileUri && styles.pickerSelected]}
        onPress={pickFile}
        disabled={isActive}
      >
        <Text style={styles.pickerIcon}>📦</Text>
        {fileUri ? (
          <>
            <Text style={styles.pickerFilename} numberOfLines={1}>{fileName}</Text>
            <Text style={styles.pickerSize}>{(fileSize / 1024 / 1024).toFixed(1)} MB</Text>
          </>
        ) : (
          <Text style={styles.pickerHint}>Tap to select a ZIP file</Text>
        )}
      </TouchableOpacity>

      {/* Date format */}
      <View style={styles.field}>
        <Text style={styles.label}>Date format in filenames</Text>
        <TextInput
          style={styles.input}
          value={dateFormat}
          onChangeText={setDateFormat}
          placeholder="%Y%m%d_%H%M%S"
          placeholderTextColor={COLORS.textSecondary}
          editable={!isActive}
          autoCapitalize="none"
          autoCorrect={false}
        />
        <Text style={styles.hint}>Python strptime format (e.g. %Y%m%d_%H%M%S_000)</Text>
      </View>

      {/* Upload button */}
      {!isActive && !isDone && (
        <TouchableOpacity
          style={[styles.uploadBtn, (!fileUri || !dateFormat.trim()) && styles.uploadBtnDisabled]}
          onPress={startUpload}
          disabled={!fileUri || !dateFormat.trim()}
        >
          <Text style={styles.uploadBtnText}>Upload</Text>
        </TouchableOpacity>
      )}

      {/* Progress */}
      {(isActive || isDone || isError) && (
        <View style={styles.progressCard}>
          <Text style={styles.progressLabel}>{statusMsg}</Text>

          {/* Progress bar */}
          <View style={styles.progressBar}>
            <View style={[
              styles.progressFill,
              { width: `${Math.round(totalProgress * 100)}%` },
              isDone && styles.progressFillDone,
              isError && styles.progressFillError,
            ]} />
          </View>
          <Text style={styles.progressPct}>{Math.round(totalProgress * 100)}%</Text>

          {phase === 'processing' && (
            <ActivityIndicator color={COLORS.primary} style={{ marginTop: 8 }} />
          )}

          {isDone && (
            <TouchableOpacity style={styles.doneBtn} onPress={reset}>
              <Text style={styles.doneBtnText}>Upload another file</Text>
            </TouchableOpacity>
          )}

          {isError && (
            <TouchableOpacity style={styles.retryBtn} onPress={reset}>
              <Text style={styles.retryBtnText}>Try again</Text>
            </TouchableOpacity>
          )}

          {isActive && (
            <TouchableOpacity style={styles.cancelBtn} onPress={cancel}>
              <Text style={styles.cancelBtnText}>Cancel</Text>
            </TouchableOpacity>
          )}
        </View>
      )}
    </ScrollView>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.background },
  content: { padding: 16, paddingBottom: 48 },
  title: { fontSize: 22, fontWeight: '700', color: COLORS.purple, marginBottom: 20 },

  picker: {
    backgroundColor: COLORS.surface, borderRadius: 14, padding: 20,
    alignItems: 'center', borderWidth: 2, borderColor: COLORS.divider,
    borderStyle: 'dashed', gap: 6, marginBottom: 16,
  },
  pickerSelected: { borderColor: COLORS.primary, borderStyle: 'solid' },
  pickerIcon: { fontSize: 32 },
  pickerFilename: { fontSize: 14, fontWeight: '600', color: COLORS.textPrimary, maxWidth: 260 },
  pickerSize: { fontSize: 12, color: COLORS.textSecondary },
  pickerHint: { fontSize: 14, color: COLORS.textSecondary },

  field: { marginBottom: 16 },
  label: { fontSize: 13, fontWeight: '600', color: COLORS.textPrimary, marginBottom: 6 },
  input: {
    backgroundColor: COLORS.surface, borderRadius: 10, paddingHorizontal: 14, paddingVertical: 10,
    fontSize: 14, color: COLORS.textPrimary, borderWidth: 1, borderColor: COLORS.divider,
  },
  hint: { fontSize: 11, color: COLORS.textSecondary, marginTop: 4 },

  uploadBtn: {
    backgroundColor: COLORS.primary, borderRadius: 12, paddingVertical: 14,
    alignItems: 'center', marginTop: 4,
  },
  uploadBtnDisabled: { opacity: 0.45 },
  uploadBtnText: { color: '#fff', fontWeight: '700', fontSize: 16 },

  progressCard: {
    backgroundColor: COLORS.surface, borderRadius: 14, padding: 20,
    marginTop: 16, gap: 8,
  },
  progressLabel: { fontSize: 13, color: COLORS.textPrimary, textAlign: 'center' },
  progressBar: {
    height: 8, backgroundColor: COLORS.divider, borderRadius: 4, overflow: 'hidden',
    marginVertical: 4,
  },
  progressFill: { height: '100%', backgroundColor: COLORS.primary, borderRadius: 4 },
  progressFillDone: { backgroundColor: '#4CAF50' },
  progressFillError: { backgroundColor: COLORS.primary },
  progressPct: { fontSize: 12, color: COLORS.textSecondary, textAlign: 'center' },

  doneBtn: {
    marginTop: 8, paddingVertical: 10, borderRadius: 10,
    backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.primary,
    alignItems: 'center',
  },
  doneBtnText: { color: COLORS.primary, fontWeight: '600' },
  retryBtn: {
    marginTop: 8, paddingVertical: 10, borderRadius: 10,
    backgroundColor: COLORS.surface, borderWidth: 1, borderColor: COLORS.primary,
    alignItems: 'center',
  },
  retryBtnText: { color: COLORS.primary, fontWeight: '600' },
  cancelBtn: { marginTop: 4, paddingVertical: 8, alignItems: 'center' },
  cancelBtnText: { color: COLORS.textSecondary, fontSize: 13 },
});

export default UploadScreen;
