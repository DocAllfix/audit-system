// @ts-nocheck
import { createContext, useState, useContext, useEffect, useCallback } from 'react';
import { api } from '@/api/apiClient';

const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [isLoading, setIsLoading] = useState(true);

  // Verifica il token in localStorage all'avvio
  useEffect(() => {
    const token = localStorage.getItem('audit-os-token');
    if (!token) {
      setIsLoading(false);
      return;
    }
    api.auth.me()
      .then(setUser)
      .catch(() => localStorage.removeItem('audit-os-token'))
      .finally(() => setIsLoading(false));
  }, []);

  /**
   * Login: chiama il backend, salva il token, imposta l'utente.
   * In caso di errore rilancia l'eccezione (gestita dal componente Login).
   */
  const login = useCallback(async (username, password) => {
    const data = await api.auth.login(username, password);
    // Il backend risponde con { token, user: { email, role, full_name } }
    localStorage.setItem('audit-os-token', data.token);
    setUser(data.user);
    return data;
  }, []);

  /**
   * Logout: invalida la sessione lato server, rimuove il token locale.
   */
  const logout = useCallback(async () => {
    try {
      await api.auth.logout();
    } catch {
      // ignora errori di rete — rimuoviamo il token comunque
    }
    localStorage.removeItem('audit-os-token');
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{
      user,
      isLoading,
      isAuthenticated: !!user,
      login,
      logout,
    }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth deve essere usato dentro AuthProvider');
  return ctx;
};
