import React, { useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { NativeStackNavigationProp } from '@react-navigation/native-stack';
import { axiosInstance, COLORS } from '../constants';
import { RootStackParamList } from '../types';

type Props = {
  navigation: NativeStackNavigationProp<RootStackParamList, 'Register'>;
};

const RegisterScreen = ({ navigation }: Props) => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [loading, setLoading] = useState(false);

  const handleRegister = async () => {
    if (!username.trim() || !password.trim()) {
      Alert.alert('Error', 'Please fill in all fields');
      return;
    }
    if (password !== confirm) {
      Alert.alert('Error', 'Passwords do not match');
      return;
    }
    setLoading(true);
    try {
      await axiosInstance.post('/auth/register', { username, password });
      Alert.alert('Success', 'Account created. Please log in.', [
        { text: 'OK', onPress: () => navigation.replace('Login') },
      ]);
    } catch (e: any) {
      Alert.alert('Registration failed', e?.response?.data?.detail ?? 'Please try again');
    } finally {
      setLoading(false);
    }
  };

  return (
    <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <ScrollView contentContainerStyle={styles.container} keyboardShouldPersistTaps="handled">
        <Text style={styles.title}>Create Account</Text>

        <View style={styles.card}>
          {(['Username', 'Password', 'Confirm Password'] as const).map((label, i) => (
            <React.Fragment key={label}>
              <Text style={[styles.label, i > 0 && { marginTop: 16 }]}>{label}</Text>
              <TextInput
                style={styles.input}
                value={i === 0 ? username : i === 1 ? password : confirm}
                onChangeText={i === 0 ? setUsername : i === 1 ? setPassword : setConfirm}
                secureTextEntry={i > 0}
                autoCapitalize="none"
                placeholder={`Enter ${label.toLowerCase()}`}
                placeholderTextColor={COLORS.textSecondary}
              />
            </React.Fragment>
          ))}

          <TouchableOpacity
            style={[styles.button, loading && styles.buttonDisabled]}
            onPress={handleRegister}
            disabled={loading}
          >
            {loading ? <ActivityIndicator color="#fff" /> : <Text style={styles.buttonText}>Register</Text>}
          </TouchableOpacity>

          <TouchableOpacity style={styles.linkButton} onPress={() => navigation.navigate('Login')}>
            <Text style={styles.linkText}>Already have an account? Login</Text>
          </TouchableOpacity>
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
};

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: COLORS.background },
  container: { flexGrow: 1, alignItems: 'center', justifyContent: 'center', padding: 24 },
  title: { fontSize: 28, fontWeight: '700', color: COLORS.purple, marginBottom: 24 },
  card: {
    width: '100%', maxWidth: 400, backgroundColor: COLORS.surface,
    borderRadius: 16, padding: 24, elevation: 4,
  },
  label: { fontSize: 13, fontWeight: '600', color: COLORS.textPrimary, marginBottom: 6 },
  input: {
    borderWidth: 1, borderColor: COLORS.divider, borderRadius: 10,
    paddingHorizontal: 14, paddingVertical: 10, fontSize: 15, color: COLORS.textPrimary,
  },
  button: { marginTop: 24, backgroundColor: COLORS.primary, borderRadius: 10, paddingVertical: 13, alignItems: 'center' },
  buttonDisabled: { opacity: 0.6 },
  buttonText: { color: '#fff', fontWeight: '700', fontSize: 15 },
  linkButton: { marginTop: 16, alignItems: 'center' },
  linkText: { color: COLORS.secondary, fontSize: 13 },
});

export default RegisterScreen;
