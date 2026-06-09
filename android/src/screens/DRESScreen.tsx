import React, { useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { COLORS } from '../constants';
import { useAppDispatch, useAppSelector } from '../store';
import {
  addSubmission,
  clearSubmissions,
  dresLogin,
  dresLogout,
  setCurrentTask,
  setEvaluation,
} from '../store/slices/dresSlice';
import {
  dresLoginApi,
  getActiveEvaluations,
  getCurrentTask,
  submitTextToDRES,
  SubmitVerdict,
} from '../api/dres';

const POLL_MS = 10_000;

const VERDICT_COLOR: Record<SubmitVerdict, string> = {
  CORRECT: '#155724',
  INCORRECT: '#721c24',
  INDETERMINATE: '#856404',
  INVALID: '#721c24',
  ERROR: '#383d41',
};
const VERDICT_BG: Record<SubmitVerdict, string> = {
  CORRECT: '#d4edda',
  INCORRECT: '#f8d7da',
  INDETERMINATE: '#fff3cd',
  INVALID: '#f8d7da',
  ERROR: '#e2e3e5',
};
const VERDICT_ICON: Record<SubmitVerdict, string> = {
  CORRECT: '✓',
  INCORRECT: '✗',
  INDETERMINATE: '?',
  INVALID: '!',
  ERROR: '⚠',
};

const DRESScreen = () => {
  const dispatch = useAppDispatch();
  const { sessionId, evaluationId, currentTask, submissions } = useAppSelector(s => s.dres);

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [loggingIn, setLoggingIn] = useState(false);
  const [evaluations, setEvaluations] = useState<{ id: string; name: string }[]>([]);
  const [loadingEvals, setLoadingEvals] = useState(false);
  const [textAnswer, setTextAnswer] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const isLoggedIn = !!sessionId;

  // Auto-login from storage
  useEffect(() => {
    AsyncStorage.getItem('dresSessionId').then(sid => {
      if (sid) { doAutoLogin(sid); }
    });
  }, []);

  // Poll current task
  useEffect(() => {
    if (!evaluationId || !sessionId) { return; }
    const fetchTask = () =>
      getCurrentTask(evaluationId, sessionId)
        .then(data => dispatch(setCurrentTask(data)))
        .catch(() => dispatch(setCurrentTask(null)));
    fetchTask();
    const id = setInterval(fetchTask, POLL_MS);
    return () => clearInterval(id);
  }, [evaluationId, sessionId]);

  const fetchEvaluations = async (sid: string) => {
    setLoadingEvals(true);
    try {
      const evs = await getActiveEvaluations(sid);
      setEvaluations(evs);
      if (evs.length > 0 && !evaluationId) { dispatch(setEvaluation(evs[0].id)); }
    } catch {
      Alert.alert('DRES', 'Failed to load evaluations');
    } finally {
      setLoadingEvals(false);
    }
  };

  const doAutoLogin = async (sid: string) => {
    dispatch(dresLogin(sid));
    await fetchEvaluations(sid);
  };

  const handleLogin = async () => {
    if (!username.trim() || !password.trim()) { return; }
    setLoggingIn(true);
    try {
      const sid = await dresLoginApi(username, password);
      await AsyncStorage.setItem('dresSessionId', sid);
      dispatch(dresLogin(sid));
      await fetchEvaluations(sid);
    } catch (e: any) {
      Alert.alert('Login failed', e?.response?.data?.message ?? 'Check credentials');
    } finally {
      setLoggingIn(false);
    }
  };

  const handleLogout = async () => {
    dispatch(dresLogout());
    setEvaluations([]);
    await AsyncStorage.removeItem('dresSessionId');
  };

  const handleTextSubmit = async () => {
    if (!evaluationId || !sessionId || !textAnswer.trim()) { return; }
    setSubmitting(true);
    try {
      const result = await submitTextToDRES(textAnswer.trim(), evaluationId, sessionId);
      dispatch(addSubmission({
        type: 'text',
        content: textAnswer.trim(),
        verdict: result.verdict,
        message: result.message,
        ts: new Date().toISOString(),
      }));
      setTextAnswer('');
      Alert.alert(
        result.verdict,
        result.message || result.verdict,
        [{ text: 'OK' }],
      );
    } catch {
      Alert.alert('Error', 'Submission failed');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      <Text style={styles.title}>DRES Competition</Text>

      {!isLoggedIn ? (
        /* ── Login ── */
        <View style={styles.card}>
          <Text style={styles.sectionLabel}>Login to DRES</Text>
          <TextInput
            style={styles.input}
            placeholder="Username"
            placeholderTextColor={COLORS.textSecondary}
            value={username}
            onChangeText={setUsername}
            autoCapitalize="none"
            onSubmitEditing={handleLogin}
          />
          <TextInput
            style={[styles.input, { marginTop: 10 }]}
            placeholder="Password"
            placeholderTextColor={COLORS.textSecondary}
            value={password}
            onChangeText={setPassword}
            secureTextEntry
            onSubmitEditing={handleLogin}
          />
          <TouchableOpacity
            style={[styles.btn, loggingIn && styles.btnDisabled]}
            onPress={handleLogin}
            disabled={loggingIn}
          >
            {loggingIn
              ? <ActivityIndicator color="#fff" />
              : <Text style={styles.btnText}>Login</Text>}
          </TouchableOpacity>
        </View>
      ) : (
        <>
          {/* ── Status + logout ── */}
          <View style={styles.card}>
            <View style={styles.row}>
              <View style={styles.connectedBadge}>
                <Text style={styles.connectedText}>● Connected</Text>
              </View>
              <TouchableOpacity onPress={handleLogout}>
                <Text style={styles.logoutText}>Logout</Text>
              </TouchableOpacity>
            </View>
          </View>

          {/* ── Evaluation selector ── */}
          <View style={styles.card}>
            <View style={styles.row}>
              <Text style={styles.sectionLabel}>Evaluation</Text>
              <TouchableOpacity
                onPress={() => fetchEvaluations(sessionId)}
                style={styles.refreshBtn}
                disabled={loadingEvals}
              >
                {loadingEvals
                  ? <ActivityIndicator size="small" color={COLORS.secondary} />
                  : <Text style={styles.refreshText}>↻ Refresh</Text>}
              </TouchableOpacity>
            </View>
            {evaluations.map(ev => (
              <TouchableOpacity
                key={ev.id}
                style={[styles.evalRow, evaluationId === ev.id && styles.evalRowActive]}
                onPress={() => dispatch(setEvaluation(ev.id))}
              >
                <Text style={[styles.evalText, evaluationId === ev.id && styles.evalTextActive]}>
                  {ev.name}
                </Text>
                {evaluationId === ev.id && <Text style={styles.evalCheck}>✓</Text>}
              </TouchableOpacity>
            ))}
            {evaluations.length === 0 && !loadingEvals && (
              <Text style={styles.noEval}>No active evaluations</Text>
            )}
          </View>

          {/* ── Current task ── */}
          {evaluationId && (
            <View style={[styles.card, styles.taskCard]}>
              <Text style={styles.sectionLabel}>Current Task</Text>
              {currentTask ? (
                <>
                  <Text style={styles.taskName}>{currentTask.name}</Text>
                  <View style={styles.taskMeta}>
                    <TaskBadge label={currentTask.taskGroup} />
                    <TaskBadge label={currentTask.taskType} accent />
                    <TaskBadge label={`${currentTask.duration}s`} />
                  </View>
                </>
              ) : (
                <Text style={styles.noEval}>No active task</Text>
              )}
            </View>
          )}

          {/* ── Text answer ── */}
          {evaluationId && (
            <View style={styles.card}>
              <Text style={styles.sectionLabel}>
                {currentTask?.taskType === 'QA' ? 'QA Answer' : 'Text Answer'}
              </Text>
              <TextInput
                style={styles.input}
                placeholder="Type answer…"
                placeholderTextColor={COLORS.textSecondary}
                value={textAnswer}
                onChangeText={setTextAnswer}
                multiline
                returnKeyType="send"
                onSubmitEditing={handleTextSubmit}
              />
              <TouchableOpacity
                style={[
                  styles.btn,
                  styles.submitBtn,
                  (!textAnswer.trim() || submitting) && styles.btnDisabled,
                ]}
                onPress={handleTextSubmit}
                disabled={!textAnswer.trim() || submitting}
              >
                {submitting
                  ? <ActivityIndicator color="#fff" />
                  : <Text style={styles.btnText}>Submit Text</Text>}
              </TouchableOpacity>
            </View>
          )}

          {/* ── Submission history ── */}
          {submissions.length > 0 && (
            <View style={styles.card}>
              <View style={styles.row}>
                <Text style={styles.sectionLabel}>Submission History</Text>
                <TouchableOpacity onPress={() => dispatch(clearSubmissions())}>
                  <Text style={styles.logoutText}>Clear</Text>
                </TouchableOpacity>
              </View>
              {submissions.map((s, i) => (
                <View
                  key={i}
                  style={[
                    styles.submissionRow,
                    { backgroundColor: VERDICT_BG[s.verdict] },
                  ]}
                >
                  <Text style={[styles.submissionIcon, { color: VERDICT_COLOR[s.verdict] }]}>
                    {VERDICT_ICON[s.verdict]}
                  </Text>
                  <View style={styles.submissionBody}>
                    <Text
                      style={[styles.submissionVerdict, { color: VERDICT_COLOR[s.verdict] }]}
                    >
                      {s.verdict}
                    </Text>
                    <Text style={styles.submissionContent} numberOfLines={1}>
                      {s.type === 'image' ? '🖼 ' : '💬 '}{s.content}
                    </Text>
                    {s.message ? (
                      <Text style={styles.submissionMessage} numberOfLines={2}>{s.message}</Text>
                    ) : null}
                  </View>
                  <Text style={styles.submissionTime}>
                    {new Date(s.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </Text>
                </View>
              ))}
            </View>
          )}
        </>
      )}
    </ScrollView>
  );
};

const TaskBadge = ({ label, accent }: { label: string; accent?: boolean }) => (
  <View style={[styles.badge, accent && styles.badgeAccent]}>
    <Text style={[styles.badgeText, accent && styles.badgeTextAccent]}>{label}</Text>
  </View>
);

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.background },
  content: { padding: 16, paddingBottom: 40 },
  title: { fontSize: 22, fontWeight: '700', color: COLORS.purple, marginBottom: 16 },
  card: {
    backgroundColor: COLORS.surface, borderRadius: 14, padding: 16,
    marginBottom: 12, elevation: 2, gap: 8,
  },
  taskCard: { borderLeftWidth: 4, borderLeftColor: COLORS.secondary },
  sectionLabel: {
    fontSize: 11, fontWeight: '700', color: COLORS.textSecondary,
    textTransform: 'uppercase', letterSpacing: 0.5,
  },
  input: {
    borderWidth: 1, borderColor: COLORS.divider, borderRadius: 10,
    paddingHorizontal: 12, paddingVertical: 9, fontSize: 14, color: COLORS.textPrimary,
  },
  btn: {
    backgroundColor: COLORS.primary, borderRadius: 10,
    paddingVertical: 12, alignItems: 'center',
  },
  submitBtn: { backgroundColor: COLORS.secondary },
  btnDisabled: { opacity: 0.45 },
  btnText: { color: '#fff', fontWeight: '700', fontSize: 14 },
  row: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  connectedBadge: {
    backgroundColor: '#d4edda', paddingHorizontal: 10, paddingVertical: 4, borderRadius: 20,
  },
  connectedText: { color: '#155724', fontSize: 12, fontWeight: '600' },
  logoutText: { color: COLORS.primary, fontSize: 13, fontWeight: '600' },
  refreshBtn: { paddingVertical: 2 },
  refreshText: { fontSize: 12, color: COLORS.secondary, fontWeight: '600' },
  evalRow: {
    paddingVertical: 10, paddingHorizontal: 12, borderRadius: 8,
    borderWidth: 1, borderColor: COLORS.divider,
    flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center',
  },
  evalRowActive: { backgroundColor: COLORS.secondary, borderColor: COLORS.secondary },
  evalText: { fontSize: 13, color: COLORS.textPrimary, flex: 1 },
  evalTextActive: { color: '#fff', fontWeight: '600' },
  evalCheck: { color: '#fff', fontWeight: '700' },
  noEval: { fontSize: 13, color: COLORS.textSecondary, fontStyle: 'italic' },
  taskName: { fontSize: 15, fontWeight: '700', color: COLORS.textPrimary },
  taskMeta: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  badge: {
    paddingHorizontal: 8, paddingVertical: 3, borderRadius: 8,
    backgroundColor: COLORS.background, borderWidth: 1, borderColor: COLORS.divider,
  },
  badgeAccent: { backgroundColor: COLORS.secondary, borderColor: COLORS.secondary },
  badgeText: { fontSize: 11, color: COLORS.textSecondary },
  badgeTextAccent: { color: '#fff', fontWeight: '600' },
  submissionRow: {
    flexDirection: 'row', alignItems: 'flex-start', borderRadius: 8,
    padding: 10, gap: 8,
  },
  submissionIcon: { fontSize: 16, fontWeight: '700', width: 18, textAlign: 'center', marginTop: 1 },
  submissionBody: { flex: 1 },
  submissionVerdict: { fontSize: 11, fontWeight: '700', textTransform: 'uppercase', letterSpacing: 0.4 },
  submissionContent: { fontSize: 12, color: COLORS.textPrimary, marginTop: 1 },
  submissionMessage: { fontSize: 11, color: COLORS.textSecondary, marginTop: 2 },
  submissionTime: { fontSize: 10, color: COLORS.textSecondary, marginTop: 2 },
});

export default DRESScreen;
