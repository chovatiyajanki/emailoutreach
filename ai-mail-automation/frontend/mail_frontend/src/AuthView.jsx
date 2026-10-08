import React, { useState } from 'react'

export default function AuthView({ onAuthSuccess, apiBase }) {
  const [isLogin, setIsLogin] = useState(true)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [fullName, setFullName] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [errorMsg, setErrorMsg] = useState('')
  const [successMsg, setSuccessMsg] = useState('')

  const handleToggleMode = (mode) => {
    setIsLogin(mode)
    setErrorMsg('')
    setSuccessMsg('')
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setErrorMsg('')
    setSuccessMsg('')

    const cleanEmail = email.trim().toLowerCase()
    if (!cleanEmail) {
      setErrorMsg('Please enter your email address.')
      return
    }

    if (!cleanEmail.includes('@') || !cleanEmail.includes('.')) {
      setErrorMsg('Please enter a valid email address.')
      return
    }

    if (!password) {
      setErrorMsg('Please enter your password.')
      return
    }

    if (!isLogin) {
      if (password.length < 6) {
        setErrorMsg('Password must be at least 6 characters long.')
        return
      }
      if (password !== confirmPassword) {
        setErrorMsg('Passwords do not match. Please verify your password.')
        return
      }
    }

    setIsLoading(true)
    const endpoint = isLogin ? `${apiBase}/api/auth/login` : `${apiBase}/api/auth/signup`
    const payload = isLogin
      ? { email: cleanEmail, password }
      : { email: cleanEmail, password, full_name: fullName.trim() || undefined }

    try {
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })

      const data = await res.json().catch(() => ({}))
      if (res.ok && data.success && data.access_token) {
        if (!isLogin) {
          // After successful signup: redirect to login tab instead of dashboard
          setSuccessMsg('Account created successfully! Please sign in with your email and password.')
          setIsLogin(true)
          setPassword('')
          setConfirmPassword('')
          return
        }
        setSuccessMsg(data.message || 'Signed in successfully.')
        setTimeout(() => {
          onAuthSuccess(data.access_token, data.user)
        }, 300)
      } else {
        setErrorMsg(data.detail || data.message || 'Authentication failed. Please try again.')
      }
    } catch (err) {
      setErrorMsg(`Connection error: ${err.message || 'Unable to reach backend server. Please verify backend is running.'}`)
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="auth-page-container">
      <div className="auth-card">
        {/* Brand Header */}
        <div className="auth-brand-header">
          <div className="auth-brand-logo">
            <span className="auth-logo-badge">EOS</span>
          </div>
          <h1 className="auth-title">Email Outreach Scraper</h1>
          <p className="auth-subtitle">
            Autonomous B2B lead scraping, email verification, and personalized outreach
          </p>
        </div>

        {/* Tab Toggle */}
        <div className="auth-tab-strip">
          <button
            type="button"
            className={`auth-tab-btn ${isLogin ? 'active' : ''}`}
            onClick={() => handleToggleMode(true)}
          >
            Sign In
          </button>
          <button
            type="button"
            className={`auth-tab-btn ${!isLogin ? 'active' : ''}`}
            onClick={() => handleToggleMode(false)}
          >
            Create Account
          </button>
        </div>

        {/* Status Alerts */}
        {errorMsg && (
          <div className="auth-alert error">
            <span className="auth-alert-prefix">[Error]</span>
            <span>{errorMsg}</span>
          </div>
        )}

        {successMsg && (
          <div className="auth-alert success">
            <span className="auth-alert-prefix">[OK]</span>
            <span>{successMsg}</span>
          </div>
        )}

        {/* Form */}
        <form onSubmit={handleSubmit} className="auth-form" noValidate>
          {!isLogin && (
            <div className="auth-form-group">
              <label className="auth-label">Full Name</label>
              <input
                type="text"
                className="auth-input"
                placeholder="e.g. Janki Chovatiya"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                autoComplete="name"
                disabled={isLoading}
              />
            </div>
          )}

          <div className="auth-form-group">
            <label className="auth-label">
              Email Address <span className="field-required">*</span>
            </label>
            <input
              type="email"
              className="auth-input"
              placeholder="e.g. contact@yourdomain.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              required
              disabled={isLoading}
            />
          </div>

          <div className="auth-form-group">
            <label className="auth-label">
              Password <span className="field-required">*</span>
            </label>
            <div className="auth-password-wrapper">
              <input
                type={showPassword ? 'text' : 'password'}
                className="auth-input auth-password-input"
                placeholder={isLogin ? 'Enter your password' : 'Create a secure password (min 6 chars)'}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete={isLogin ? 'current-password' : 'new-password'}
                required
                disabled={isLoading}
              />
              <button
                type="button"
                className="btn-toggle-eye"
                onClick={() => setShowPassword(!showPassword)}
                tabIndex={-1}
              >
                {showPassword ? 'Hide' : 'Show'}
              </button>
            </div>
            {!isLogin && (
              <span className="auth-field-hint">Must be at least 6 characters long</span>
            )}
          </div>

          {!isLogin && (
            <div className="auth-form-group">
              <label className="auth-label">
                Confirm Password <span className="field-required">*</span>
              </label>
              <input
                type={showPassword ? 'text' : 'password'}
                className="auth-input"
                placeholder="Re-enter password to confirm"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                autoComplete="new-password"
                required
                disabled={isLoading}
              />
            </div>
          )}

          <button
            type="submit"
            className="btn-auth-submit"
            disabled={isLoading}
          >
            {isLoading
              ? (isLogin ? 'Signing In...' : 'Creating Account...')
              : (isLogin ? 'Sign In to Dashboard' : 'Create Free Account')}
          </button>
        </form>

        {/* Footer Toggle Link */}
        <div className="auth-card-footer">
          {isLogin ? (
            <p>
              Do not have an account yet?{' '}
              <button
                type="button"
                className="auth-link-btn"
                onClick={() => handleToggleMode(false)}
              >
                Create one now
              </button>
            </p>
          ) : (
            <p>
              Already registered?{' '}
              <button
                type="button"
                className="auth-link-btn"
                onClick={() => handleToggleMode(true)}
              >
                Sign in to your account
              </button>
            </p>
          )}
        </div>

        {/* Security Note */}
        <div className="auth-security-note">
          <span>Secured with standard JWT &amp; bcrypt password hashing</span>
        </div>
      </div>
    </div>
  )
}
