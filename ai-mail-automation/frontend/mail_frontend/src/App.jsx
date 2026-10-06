import { useState, useEffect, useRef } from 'react'
import './App.css'
import RichTextEditor, { ensureHtmlContent } from './RichTextEditor'

const MAIL_PRESETS = [
  {
    label: ' B2B Cold Outreach',
    subject: 'Partnership & Automation Opportunities for {{company_name}}',
    body: "<p>Hi {{company_name}} Team,</p><p>I came across <b>{{website}}</b> and noticed your work in <i>{{industry}}</i> across {{city}}. Our platform automates B2B email workflows and communication pipelines.</p><p>Would you be open to a brief <b>10-minute demo</b> next week to see how we can reduce manual outreach by 40%?</p><p>Best regards,<br><b>{{sender_name}}</b></p>"
  },
  {
    label: ' Business Collaboration',
    subject: 'Potential collaboration with {{company_name}} in {{city}}',
    body: "<p>Hi there,</p><p>I've been following <b>{{company_name}}</b>'s recent growth in {{city}}. We collaborate with leading {{industry}} companies to streamline client engagement and outreach.</p><p>Are you available for a quick chat this Thursday to explore mutual synergies?</p><p>Best,<br><b>{{sender_name}}</b></p>"
  },
  {
    label: ' 10-Min Demo Request',
    subject: 'Quick question for {{company_name}} leadership',
    body: "<p>Hello {{company_name}} Team,</p><p>I checked out <b>{{website}}</b> and was impressed by your execution in the {{industry}} space. We built an automated system specifically helping companies like yours eliminate outreach bottlenecks.</p><p>Would you have <b>10 minutes</b> next Tuesday or Wednesday for a quick look?</p><p>Cheers,<br><b>{{sender_name}}</b></p>"
  },
  {
    label: ' Healthcare & Supplies',
    subject: 'Supply chain & inventory automation for {{company_name}}',
    body: "<p>Dear {{company_name}} Management,</p><p>We support healthcare facilities and pharmacies in <b>{{city}}</b> with verified supplier pipelines and automated ordering workflows.</p><p>Could we share a 2-page brief on how we help {{industry}} providers optimize their procurement?</p><p>Warm regards,<br><b>{{sender_name}}</b></p>"
  },
  {
    label: ' Local Business Growth',
    subject: 'Growth opportunities for {{company_name}} in {{city}}',
    body: "<p>Hi {{company_name}} Team,</p><p>We are actively working with premier <b>{{industry}}</b> businesses in {{city}} to scale their local outreach and client acquisitions.</p><p>I'd love to share two quick ideas tailored to <b>{{website}}</b>. Do you have 5 minutes this week?</p><p>Best regards,<br><b>{{sender_name}}</b></p>"
  }
]

const API_BASE = (
  import.meta.env.VITE_API_URL ||
  (typeof window !== 'undefined' &&
  (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
    ? 'http://localhost:8000'
    : 'https://emailoutreach-84dr.onrender.com')
).replace(/\/$/, '')

// Helper to format any UTC or ISO timestamp into clean user local time (e.g. IST)
function formatLocalDateTime(val, includeSeconds = false) {
  if (!val) return '—'
  let str = String(val).trim()
  if (!str) return '—'
  // If no timezone offset (+/-) and no Z, assume UTC from backend database
  if (!str.endsWith('Z') && !/[+-]\d{2}(:?\d{2})?$/.test(str)) {
    str = str.replace(' ', 'T') + 'Z'
  }
  const d = new Date(str)
  if (isNaN(d.getTime())) return val

  const pad = (n) => String(n).padStart(2, '0')
  const yyyy = d.getFullYear()
  const mm = pad(d.getMonth() + 1)
  const dd = pad(d.getDate())
  let hours = d.getHours()
  const minutes = pad(d.getMinutes())
  const seconds = pad(d.getSeconds())
  const ampm = hours >= 12 ? 'PM' : 'AM'
  const h12 = pad(hours % 12 || 12)

  return includeSeconds
    ? `${yyyy}-${mm}-${dd} ${h12}:${minutes}:${seconds} ${ampm}`
    : `${yyyy}-${mm}-${dd} ${h12}:${minutes} ${ampm}`
}

export default function App() {
  // Current active data tab: 'accounts' | 'sent' | 'undelivered' | 'replies' | 'runs'
  const [activeTab, setActiveTab] = useState('accounts')

  // Search filter inside tables
  const [searchQuery, setSearchQuery] = useState('')

  // Detail viewer modal
  const [selectedRecord, setSelectedRecord] = useState(null)

  // Execution states
  const [isTriggering, setIsTriggering] = useState(false)
  const [feedbackMsg, setFeedbackMsg] = useState('')

  // Scheduler backend state
  const [status, setStatus] = useState({
    is_running: false,
    interval_seconds: 60,
    search_query: '',
    scrape_batch_size: 5,
    send_batch_size: 5,
    seconds_until_next_run: null,
    total_runs: 0,
    summary: {
      step_1_scraped_accounts: 0,
      step_2_found_accounts: 0,
      step_3_sent_emails: 0,
      step_4_undelivered_emails: 0,
      step_5_replies_found: 0,
    },
    mailbox: {
      email: '',
      name: '',
      smtp_host: '',
      is_configured: false,
      status: 'not_configured',
    },
    ai: {
      provider: 'Groq',
      model: 'openai/gpt-oss-120b',
      is_configured: false,
      status: 'not_configured',
    },
  })

  // Editable config state (User-controlled, NEVER overwritten by polling)
  const [editQuery, setEditQuery] = useState('')
  const [editInterval, setEditInterval] = useState('')
  const [editScrapeBatch, setEditScrapeBatch] = useState('')
  const [editSendBatch, setEditSendBatch] = useState('')
  const hasInitializedConfig = useRef(false)
  const isFetchingRef = useRef(false)

  // Campaign modal and configuration state
  const [isCampaignModalOpen, setIsCampaignModalOpen] = useState(false)
  const [campaignName, setCampaignName] = useState('')
  const [campaignSubject, setCampaignSubject] = useState('')
  const [campaignBody, setCampaignBody] = useState('')

  // Dedicated Mail Editor and Customization state
  const [isMailEditorOpen, setIsMailEditorOpen] = useState(false)
  const [editorSubject, setEditorSubject] = useState('')
  const [editorBody, setEditorBody] = useState('')
  const [isEnhancing, setIsEnhancing] = useState(false)
  const [enhanceTone, setEnhanceTone] = useState('persuasive')
  const [isSavingTemplate, setIsSavingTemplate] = useState(false)

  // SMTP Settings modal and configuration state
  const [isSmtpModalOpen, setIsSmtpModalOpen] = useState(false)
  const [smtpHost, setSmtpHost] = useState('')
  const [smtpPort, setSmtpPort] = useState('')
  const [smtpUsername, setSmtpUsername] = useState('')
  const [smtpPassword, setSmtpPassword] = useState('')
  const [smtpSenderName, setSmtpSenderName] = useState('')
  const [showSmtpPassword, setShowSmtpPassword] = useState(false)
  const [smtpTesting, setSmtpTesting] = useState(false)
  const [smtpSaving, setSmtpSaving] = useState(false)
  const [smtpTestResult, setSmtpTestResult] = useState(null)

  // Table records state
  const [campaigns, setCampaigns] = useState([])
  const [accounts, setAccounts] = useState([])
  const [sentMails, setSentMails] = useState([])
  const [undeliveredMails, setUndeliveredMails] = useState([])
  const [bouncedMails, setBouncedMails] = useState([])
  const [blockedMails, setBlockedMails] = useState([])
  const [replies, setReplies] = useState([])
  const [runs, setRuns] = useState([])


  // Fetch status and all data from FastAPI
  const fetchAllData = async () => {
    if (isFetchingRef.current) return
    isFetchingRef.current = true
    try {
      const [resStatus, resAccounts, resSent, resBounced, resBlocked, resUndelivered, resReplies, resRuns, resCampaigns] = await Promise.all([
        fetch(`${API_BASE}/api/scheduler/status`),
        fetch(`${API_BASE}/api/data/accounts`),
        fetch(`${API_BASE}/api/data/sent`),
        fetch(`${API_BASE}/api/data/bounced`),
        fetch(`${API_BASE}/api/data/blocked`),
        fetch(`${API_BASE}/api/data/undelivered`),
        fetch(`${API_BASE}/api/data/replies`),
        fetch(`${API_BASE}/api/scheduler/runs`),
        fetch(`${API_BASE}/api/campaigns`),
      ])

      if (resStatus.ok) {
        const data = await resStatus.json()
        setStatus(data)
        // ONLY initialize input fields once on initial mount!
        // NEVER overwrite inputs during background polling!
        if (!hasInitializedConfig.current) {
          hasInitializedConfig.current = true
        }
      }
      if (resAccounts.ok) setAccounts(await resAccounts.json())
      if (resSent.ok) setSentMails(await resSent.json())
      if (resBounced.ok) setBouncedMails(await resBounced.json())
      if (resBlocked.ok) setBlockedMails(await resBlocked.json())
      if (resUndelivered.ok) setUndeliveredMails(await resUndelivered.json())
      if (resReplies.ok) setReplies(await resReplies.json())
      if (resRuns.ok) setRuns(await resRuns.json())
      if (resCampaigns && resCampaigns.ok) {
        const cData = await resCampaigns.json()
        setCampaigns(cData.campaigns || [])
      }
    } catch {
      // Backend polling error
    } finally {
      isFetchingRef.current = false
    }
  }

  // Fetch SMTP settings from backend
  const fetchSmtpSettings = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/smtp/settings`)
      if (res.ok) {
        const data = await res.json()
        if (data.smtp_host) setSmtpHost(data.smtp_host)
        if (data.smtp_port) setSmtpPort(data.smtp_port)
        if (data.smtp_username) setSmtpUsername(data.smtp_username)
        if (data.smtp_password) setSmtpPassword(data.smtp_password)
        if (data.sender_name) setSmtpSenderName(data.sender_name)
      }
    } catch {
      // Backend offline
    }
  }

  useEffect(() => {
    fetchAllData()
    fetchSmtpSettings()
    const timer = setInterval(fetchAllData, 5000)
    return () => clearInterval(timer)
  }, [])

  // Start or Stop the automated scheduler (Instant 1-Click Response)
  const handleToggleScheduler = async () => {
    try {
      if (!status.is_running) {
        // Optimistic UI update on start
        setStatus((prev) => ({ ...prev, is_running: true }))
        setFeedbackMsg(`Starting autopilot for "${campaignName}"...`)
        await fetch(`${API_BASE}/api/scheduler/config`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            campaign_name: campaignName,
            search_query: editQuery,
            interval_seconds: Number(editInterval) || 60,
            scrape_batch_size: Number(editScrapeBatch) || 5,
            send_batch_size: Number(editSendBatch) || 5,
            email_subject: campaignSubject,
            email_body: campaignBody,
          }),
        })
        const res = await fetch(`${API_BASE}/api/scheduler/start`, { method: 'POST' })
        if (res.ok) {
          await fetchAllData()
          const intvVal = Number(editInterval) || 60
          setFeedbackMsg(`Scheduler started for "${campaignName || 'Campaign'}"! Running every ${intvVal >= 60 ? Math.round(intvVal / 60) + ' min' : intvVal + 's'}.`)
        } else {
          setStatus((prev) => ({ ...prev, is_running: false }))
          setFeedbackMsg('Failed to start scheduler.')
        }
      } else {
        // INSTANT 1-CLICK OPTIMISTIC PAUSE: Immediately change button to idle without waiting
        setStatus((prev) => ({ ...prev, is_running: false }))
        setFeedbackMsg('Autopilot paused.')
        const res = await fetch(`${API_BASE}/api/scheduler/stop`, { method: 'POST' })
        if (res.ok) {
          await fetchAllData()
        } else {
          setStatus((prev) => ({ ...prev, is_running: true }))
          setFeedbackMsg('Failed to stop scheduler on server.')
        }
      }
    } catch {
      setFeedbackMsg('Network error while toggling scheduler.')
    }
  }

  // Trigger an immediate 5-step cycle right now with current UI parameters
  const handleTriggerNow = async () => {
    setIsTriggering(true)
    setFeedbackMsg(`Executing cycle for "${editQuery || 'All Companies'}" (Scrape: ${editScrapeBatch || 5}, Send: ${editSendBatch || 5})...`)
    try {
      const res = await fetch(`${API_BASE}/api/scheduler/trigger`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          campaign_name: campaignName,
          query: editQuery,
          scrape_batch_size: Number(editScrapeBatch) || 5,
          send_batch_size: Number(editSendBatch) || 5,
          email_subject: campaignSubject,
          email_body: campaignBody,
        }),
      })
      if (res.ok) {
        await fetchAllData()
        handleSelectTab('accounts')
        setFeedbackMsg(`Cycle complete for "${editQuery || 'All Companies'}". Discovered accounts updated in DataBase!`)
      } else {
        setFeedbackMsg('Cycle encountered an error.')
      }
    } catch {
      setFeedbackMsg('Failed to run cycle. Ensure backend is active.')
    } finally {
      setIsTriggering(false)
    }
  }

  // Launch campaign: save to campaigns table and trigger immediate 5-step run
  const handleLaunchCampaign = async () => {
    setIsTriggering(true)
    setIsCampaignModalOpen(false)
    setFeedbackMsg(`Creating and launching campaign "${campaignName || 'Campaign'}" for "${editQuery || 'All Companies'}"...`)
    try {
      const res = await fetch(`${API_BASE}/api/campaigns/create`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: campaignName,
          search_query: editQuery,
          scrape_batch_size: Number(editScrapeBatch) || 5,
          send_batch_size: Number(editSendBatch) || 5,
          interval_seconds: Number(editInterval) || 60,
          email_subject: campaignSubject,
          email_body: campaignBody,
          set_active: true,
          start_cycle_now: true,
        }),
      })
      if (res.ok) {
        await fetchAllData()
        handleSelectTab('campaigns')
        setFeedbackMsg(`Campaign "${campaignName || 'Campaign'}" launched! 5-step cycle executed and metrics updated.`)
      } else {
        setFeedbackMsg('Campaign execution encountered an error.')
      }
    } catch {
      setFeedbackMsg('Failed to run campaign cycle.')
    } finally {
      setIsTriggering(false)
    }
  }

  // Save campaign and start scheduler
  const handleSaveAndStartScheduler = async () => {
    setIsCampaignModalOpen(false)
    try {
      const res = await fetch(`${API_BASE}/api/campaigns/create`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: campaignName,
          search_query: editQuery,
          interval_seconds: Number(editInterval) || 60,
          scrape_batch_size: Number(editScrapeBatch) || 5,
          send_batch_size: Number(editSendBatch) || 5,
          email_subject: campaignSubject,
          email_body: campaignBody,
          set_active: true,
          start_scheduler: true,
        }),
      })
      if (res.ok) {
        await fetchAllData()
        handleSelectTab('campaigns')
        const intvVal = Number(editInterval) || 60
        setFeedbackMsg(`Campaign "${campaignName || 'Campaign'}" saved & Scheduler started! Running every ${intvVal >= 60 ? Math.round(intvVal / 60) + ' min' : intvVal + 's'}.`)
      }
    } catch {
      setFeedbackMsg('Failed to save campaign and start scheduler.')
    }
  }

  // Save campaign as draft/standby without starting
  const handleSaveCampaignOnly = async () => {
    setIsCampaignModalOpen(false)
    try {
      const res = await fetch(`${API_BASE}/api/campaigns/create`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: campaignName,
          search_query: editQuery,
          interval_seconds: Number(editInterval) || 60,
          scrape_batch_size: Number(editScrapeBatch) || 5,
          send_batch_size: Number(editSendBatch) || 5,
          email_subject: campaignSubject,
          email_body: campaignBody,
          set_active: false,
          start_scheduler: false,
        }),
      })
      if (res.ok) {
        await fetchAllData()
        handleSelectTab('campaigns')
        setFeedbackMsg(`Campaign "${campaignName || 'Campaign'}" saved successfully.`)
      }
    } catch {
      setFeedbackMsg('Failed to save campaign.')
    }
  }

  // Activate campaign in scheduler
  const handleActivateCampaign = async (campaignId, cName) => {
    try {
      const res = await fetch(`${API_BASE}/api/campaigns/${campaignId}/activate`, {
        method: 'POST',
      })
      if (res.ok) {
        await fetchAllData()
        setFeedbackMsg(`Campaign "${cName}" is now active in scheduler.`)
      }
    } catch {
      setFeedbackMsg('Failed to activate campaign.')
    }
  }

  // Immediately run a specific campaign
  const handleRunCampaign = async (campaignId, cName) => {
    setIsTriggering(true)
    setFeedbackMsg(`Executing cycle for campaign "${cName}"...`)
    try {
      const res = await fetch(`${API_BASE}/api/campaigns/${campaignId}/run`, {
        method: 'POST',
      })
      if (res.ok) {
        await fetchAllData()
        setFeedbackMsg(`5-step cycle completed for "${cName}"!`)
      } else {
        setFeedbackMsg('Campaign run encountered an error.')
      }
    } catch {
      setFeedbackMsg('Failed to execute campaign run.')
    } finally {
      setIsTriggering(false)
    }
  }

  // Delete campaign
  const handleDeleteCampaign = async (campaignId, cName) => {
    if (!window.confirm(`Delete campaign "${cName}"? This will remove it from DataBase.`)) {
      return
    }
    try {
      const res = await fetch(`${API_BASE}/api/campaigns/${campaignId}`, {
        method: 'DELETE',
      })
      if (res.ok) {
        await fetchAllData()
        setFeedbackMsg(`Campaign "${cName}" deleted.`)
      }
    } catch {
      setFeedbackMsg('Failed to delete campaign.')
    }
  }


  // Render live preview replacing placeholders with simulated lead data
  const renderLivePreview = (text, isHtml = false) => {
    if (!text) return ''
    // If only empty HTML tags or spaces, return empty string so placeholder shows
    const stripped = text.replace(/<[^>]+>/g, '').replace(/&nbsp;/g, ' ').trim()
    if (!stripped) return ''

    const sample = {
      company_name: 'Apex Innovations',
      website: 'https://apexinnovate.com',
      city: 'Chicago, IL',
      industry: 'Technology & Cloud Solutions',
      sender_name: status.mailbox?.name || 'Outreach Specialist'
    }
    let replaced = text
      .replace(/\{\{company_name\}\}/g, sample.company_name)
      .replace(/\{\{website\}\}/g, sample.website)
      .replace(/\{\{city\}\}/g, sample.city)
      .replace(/\{\{industry\}\}/g, sample.industry)
      .replace(/\{\{sender_name\}\}/g, sample.sender_name)

    // For subject lines (plain text only), strip any accidental HTML tags
    if (!isHtml) {
      return replaced.replace(/<[^>]+>/g, '').trim()
    }

    // For email body: If plain text (does not contain html tags), wrap paragraphs in <p>
    if (!/<(p|div|br|b|i|u|h1|h2|h3|ul|ol|li|blockquote|a)[\s>]/i.test(replaced)) {
      replaced = replaced
        .split(/\n\n+/)
        .map((p) => `<p>${p.replace(/\n/g, '<br>')}</p>`)
        .join('')
    }
    return replaced
  }

  // Save email template to backend
  const handleSaveMailTemplate = async () => {
    setIsSavingTemplate(true)
    const cleanSubject = editorSubject.replace(/<[^>]+>/g, '').trim()
    try {
      const res = await fetch(`${API_BASE}/api/template/save`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          subject: cleanSubject,
          body: editorBody,
          campaign_id: status.active_campaign?.id || null,
        }),
      })
      const data = await res.json()
      if (res.ok && data.success) {
        setCampaignSubject(editorSubject)
        setCampaignBody(editorBody)
        await fetchAllData()
        setIsMailEditorOpen(false)
        setFeedbackMsg('Email template saved & applied to active outreach!')
      } else {
        alert(data.message || 'Failed to save template.')
      }
    } catch {
      alert('Error saving email template. Check backend connection.')
    } finally {
      setIsSavingTemplate(false)
    }
  }

  // AI enhance email template
  const handleEnhanceMailTemplate = async () => {
    if (!editorBody.trim()) {
      alert('Please enter some text in the body first for AI to enhance.')
      return
    }
    setIsEnhancing(true)
    setFeedbackMsg('AI is polishing and enhancing your email template...')
    try {
      const res = await fetch(`${API_BASE}/api/template/enhance`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          subject: editorSubject || 'Partnership with {{company_name}}',
          body: editorBody,
          tone: enhanceTone,
        }),
      })
      const data = await res.json()
      if (res.ok && data.success) {
        if (data.subject) setEditorSubject(data.subject)
        if (data.body) setEditorBody(data.body)
        setFeedbackMsg('Template enhanced with AI! Review and click "Save & Apply".')
      } else {
        setFeedbackMsg(data.message || 'AI enhance encountered an issue.')
      }
    } catch {
      setFeedbackMsg('Failed to enhance template. Check backend.')
    } finally {
      setIsEnhancing(false)
    }
  }


  // Fresh start: wipe all data in database
  const handleResetAllData = async () => {
    if (!window.confirm('Fresh Start: Delete all records in DataBase? This resets total runs to 0.')) {
      return
    }
    try {
      const res = await fetch(`${API_BASE}/api/reset`, { method: 'POST' })
      if (res.ok) {
        await fetchAllData()
        setFeedbackMsg('All tables reset cleanly. Fresh start initialized.')
      }
    } catch {
      alert('Failed to reset database.')
    }
  }


  // Test SMTP connection live
  const handleTestSmtp = async () => {
    setSmtpTesting(true)
    setSmtpTestResult(null)
    try {
      const res = await fetch(`${API_BASE}/api/smtp/test`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          smtp_host: smtpHost,
          smtp_port: Number(smtpPort),
          smtp_username: smtpUsername,
          smtp_password: smtpPassword,
          sender_name: smtpSenderName,
        }),
      })
      const data = await res.json()
      setSmtpTestResult(data)
    } catch {
      setSmtpTestResult({ success: false, message: 'Network error or backend unreachable.' })
    } finally {
      setSmtpTesting(false)
    }
  }

  // Save manual SMTP settings into PostgreSQL
  const handleSaveSmtp = async () => {
    setSmtpSaving(true)
    try {
      const res = await fetch(`${API_BASE}/api/smtp/settings`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          smtp_host: smtpHost,
          smtp_port: Number(smtpPort),
          smtp_username: smtpUsername,
          smtp_password: smtpPassword,
          sender_name: smtpSenderName,
        }),
      })
      if (res.ok) {
        const data = await res.json()
        setFeedbackMsg(`${data.message || 'SMTP settings saved!'}`)
        await fetchAllData()
        setIsSmtpModalOpen(false)
      } else {
        const data = await res.json()
        setFeedbackMsg(`Error: ${data.detail || 'Could not save SMTP settings'}`)
      }
    } catch {
      setFeedbackMsg('Failed to save SMTP settings. Check backend connection.')
    } finally {
      setSmtpSaving(false)
    }
  }

  // Remove / clear configured SMTP settings
  const handleRemoveSmtp = async () => {
    if (!window.confirm('Remove saved SMTP settings? This will clear your sender credentials.')) {
      return
    }
    try {
      const res = await fetch(`${API_BASE}/api/smtp/clear`, { method: 'POST' })
      if (res.ok) {
        setSmtpUsername('')
        setSmtpPassword('')
        setSmtpSenderName('')
        setSmtpTestResult(null)
        setFeedbackMsg('SMTP settings removed successfully.')
        await fetchAllData()
        setIsSmtpModalOpen(false)
      } else {
        setFeedbackMsg('Failed to remove SMTP settings.')
      }
    } catch {
      setFeedbackMsg('Network error while removing SMTP settings.')
    }
  }

  // Apply quick provider preset
  const applySmtpPreset = (preset) => {
    setSmtpTestResult(null)
    if (preset === 'hostinger') {
      setSmtpHost('smtp.hostinger.com')
      setSmtpPort(465)
    } else if (preset === 'hostinger_tls') {
      setSmtpHost('smtp.hostinger.com')
      setSmtpPort(587)
    } else if (preset === 'gmail') {
      setSmtpHost('smtp.gmail.com')
      setSmtpPort(587)
    } else if (preset === 'gmail_ssl') {
      setSmtpHost('smtp.gmail.com')
      setSmtpPort(465)
    } else if (preset === 'office365') {
      setSmtpHost('smtp.office365.com')
      setSmtpPort(587)
    } else if (preset === 'yahoo') {
      setSmtpHost('smtp.mail.yahoo.com')
      setSmtpPort(587)
    } else if (preset === 'sendgrid') {
      setSmtpHost('smtp.sendgrid.net')
      setSmtpPort(587)
    }
  }

  // Switch tab and automatically reset table search filter
  const handleSelectTab = (tab) => {
    setActiveTab(tab)
    setSearchQuery('')
  }

  // Filter items in active table
  const filterRows = (items) => {
    if (!searchQuery.trim()) return items
    const q = searchQuery.toLowerCase()
    return items.filter((row) => JSON.stringify(row).toLowerCase().includes(q))
  }

  // Render clean "no matches found" state if search filter returned 0 results
  const renderNoSearchResults = (totalCount) => (
    <div className="no-data-box">
      <h4 className="no-data-title">No matches found for &quot;{searchQuery}&quot;</h4>
      <p className="no-data-hint">
        None of the {totalCount} records in this tab matched your search term.
      </p>
      <button
        className="nav-btn"
        style={{ marginTop: '12px', padding: '6px 14px' }}
        onClick={() => setSearchQuery('')}
      >
        Clear Search Filter
      </button>
    </div>
  )

  // Strict Categorization per user request:
  // 1. Sent Mails: ONLY genuinely dispatched emails (strictly exclude bounced and blocked)
  const sentOnlyMails = sentMails.filter(
    (m) => m.status === 'sent' || m.status === 'replied' || m.status === 'replies'
  )

  // 2. Bounced Mails: ONLY recipient mailbox failures (550 mailbox not found / invalid recipient)
  const effectiveBouncedMails = bouncedMails.length > 0
    ? bouncedMails
    : undeliveredMails.filter(
        (u) =>
          !String(u.error_code || '').toLowerCase().includes('blocked') &&
          !String(u.bounce_reason || '').toLowerCase().includes('blocked')
      )

  // 3. Blocked Mails: ONLY provider policy blocks (Google 554/5.7.1 outbound sending restrictions)
  const effectiveBlockedMails = blockedMails.length > 0
    ? blockedMails
    : undeliveredMails.filter(
        (u) =>
          String(u.error_code || '').toLowerCase().includes('blocked') ||
          String(u.bounce_reason || '').toLowerCase().includes('blocked')
      )

  return (
    <div className="scheduler-app">
      {/* ====================================================================
          1. TOP NAVIGATION BAR
          ==================================================================== */}
      <header className="top-navbar">
        <div className="nav-brand">
          <div className="brand-symbol">OS</div>
          <div className="brand-details">
            <span className="brand-heading">Outreach Scheduler</span>
            <span className="brand-subtext">Automated B2B Lead Discovery &amp; Email Dispatch</span>
          </div>
        </div>

        <div className="nav-controls">
          {status.mailbox.email ? (
            <div
              className="sender-pill configured"
              title={`Active Campaign Sender: ${status.mailbox.email} via ${status.mailbox.smtp_host || 'Hostinger'}`}
            >
              <span className="live-indicator"></span>
              <span>
                {status.mailbox?.smtp_host?.toLowerCase().includes('hostinger') || smtpHost?.toLowerCase().includes('hostinger') ? '' : ''}
                {status.mailbox.email}
              </span>
            </div>
          ) : (
            <div
              className="sender-pill unconfigured"
              onClick={() => { fetchSmtpSettings(); setIsSmtpModalOpen(true); }}
              style={{ cursor: 'pointer', background: 'rgba(245, 158, 11, 0.12)', borderColor: 'rgba(245, 158, 11, 0.3)', color: '#fbbf24' }}
              title="Click to configure sender SMTP"
            >
              
              <span>Set Up SMTP Sender</span>
            </div>
          )}

          {(status.mailbox?.smtp_host?.toLowerCase().includes('hostinger') || smtpHost?.toLowerCase().includes('hostinger')) ? (
            <a
              href="https://mail.hostinger.com"
              target="_blank"
              rel="noreferrer"
              className="nav-btn hostinger-link-btn"
              title="Open Hostinger Webmail in new tab"
            >
              Hostinger Webmail
            </a>
          ) : (
            <a
              href="https://mail.google.com/mail/u/0/#inbox"
              target="_blank"
              rel="noreferrer"
              className="nav-btn"
              title="Open real Gmail Inbox"
            >
              Gmail Inbox
            </a>
          )}

          <button
            className="nav-btn btn-smtp-settings"
            onClick={() => { fetchSmtpSettings(); setIsSmtpModalOpen(true); }}
            title="Configure Hostinger or custom SMTP mail server & credentials"
          >
            SMTP Settings
          </button>

          <button className="nav-btn" onClick={fetchAllData} title="Refresh records from database">
            Refresh
          </button>

          <button
            className="btn-reset-danger"
            onClick={handleResetAllData}
            title="Delete all tables and start fresh"
          >
            Fresh Start
          </button>
        </div>
      </header>

      {/* ====================================================================
          2. MAIN BODY
          ==================================================================== */}
      <main className="main-wrapper">
        {/* SCHEDULER HERO CONTROLLER CARD */}
        <section className="scheduler-hero-card">
          <div className="hero-header-row">
            <div className="status-badge-group">
              <div className={`scheduler-status-tag ${status.is_running ? 'active' : 'idle'}`}>
                <span className="status-dot"></span>
                <span>{status.is_running ? 'AUTOPILOT RUNNING' : 'AUTOPILOT IDLE'}</span>
              </div>

              <div className="hero-meta">
                <span
                  className="hero-stat-badge highlight-created"
                  title="Total outreach campaigns created in the system"
                  onClick={() => handleSelectTab('campaigns')}
                  style={{ cursor: 'pointer' }}
                >
                  Campaigns: <strong>{status.summary?.total_campaigns_created ?? campaigns.length}</strong>
                </span>
                <span
                  className="hero-stat-badge highlight-run"
                  title="Total outreach campaigns that have been executed"
                  onClick={() => handleSelectTab('campaigns')}
                  style={{ cursor: 'pointer' }}
                >
                  Executed: <strong>{status.summary?.total_campaigns_run ?? 0}</strong>
                </span>
                <span className="hero-stat-badge" title="Total completed background cycles">
                  Cycles: <strong>{status.total_runs}</strong>
                </span>
                {status.is_running && status.seconds_until_next_run !== null && (
                  <span className="hero-stat-badge next-run-badge" style={{ background: 'rgba(245, 158, 11, 0.12)', borderColor: 'rgba(245, 158, 11, 0.35)', color: '#fde047' }}>
                    Next Cycle: <strong>{status.seconds_until_next_run}s</strong>
                  </span>
                )}
              </div>
            </div>

            <div className="hero-actions-group">
              <button
                className="btn-create-campaign"
                onClick={() => setIsCampaignModalOpen(true)}
                title="Create and configure a new outreach campaign"
              >
                New Campaign
              </button>

              <button
                className="btn-mail-editor"
                onClick={() => {
                  setEditorSubject(campaignSubject)
                  setEditorBody(campaignBody)
                  setIsMailEditorOpen(true)
                }}
                title="Edit and customize your email subject, body template, and preview"
              >
                Mail Template
              </button>

              <button
                className={`btn-toggle-scheduler ${status.is_running ? 'stop' : 'start'}`}
                onClick={handleToggleScheduler}
                title={status.is_running ? 'Pause automated background scheduler' : 'Start automated background scheduler'}
              >
                {status.is_running ? 'Pause Autopilot' : 'Start Autopilot'}
              </button>

              <button
                className="btn-trigger-now"
                disabled={isTriggering}
                onClick={handleTriggerNow}
                title="Execute 1 full 5-step cycle immediately on-demand"
              >
                {isTriggering ? 'Running Cycle...' : 'Run Cycle Now'}
              </button>
            </div>
          </div>

          {/* QUICK OUTREACH CONTROL CENTER (DIRECTLY ON DASHBOARD) */}
          <div className="dashboard-quick-control">
            <div className="quick-query-section">
              <div className="quick-input-header">
                <label className="quick-input-label">
                  Target Industry Niche, City, or Keyword:
                </label>
                <span className="quick-input-subtext">Click Run Cycle Now or Start Autopilot to execute</span>
              </div>
              <div className="quick-search-input-wrap">
                
                <input
                  type="text"
                  className="quick-search-field"
                  placeholder="e.g. Dentists in Chicago, IT companies in India, Real estate in Dubai, Ahmedabad Software..."
                  value={editQuery}
                  onChange={(e) => setEditQuery(e.target.value)}
                />
                {editQuery && (
                  <button
                    type="button"
                    className="quick-clear-btn"
                    onClick={() => setEditQuery('')}
                    title="Clear search query"
                  >
                    &times;
                  </button>
                )}
              </div>

              {/* 1-Click Popular Presets */}
              <div className="quick-presets-bar">
                <span className="quick-presets-tag">Suggestions:</span>
                {[
                  { label: 'IT in India', query: 'IT companies in India', name: 'India IT Companies Outreach' },
                  { label: 'Dentists in Chicago', query: 'Dentists in Chicago', name: 'Chicago Dentists Outreach' },
                  { label: 'Real Estate Dubai', query: 'Real estate in Dubai', name: 'Dubai Real Estate Campaign' },
                  { label: 'Medical Stores', query: 'Medical stores', name: 'Medical Stores Outreach Campaign' },
                  { label: 'Canada Agencies', query: 'Marketing agencies in Canada', name: 'Canada Marketing Agencies Campaign' },
                  { label: 'Software in USA', query: 'Software companies in USA', name: 'USA Software Companies Campaign' },
                ].map((chip) => (
                  <button
                    key={chip.query}
                    type="button"
                    className={`quick-chip-button ${editQuery === chip.query ? 'selected' : ''}`}
                    onClick={() => {
                      setEditQuery(chip.query)
                      setCampaignName(chip.name)
                    }}
                  >
                    {chip.label}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* User-Friendly Notification Banner */}
          {feedbackMsg && (
            <div className={`feedback-banner ${feedbackMsg.toLowerCase().includes('error') || feedbackMsg.toLowerCase().includes('failed') ? 'error' : 'success'}`}>
              <div className="feedback-banner-content">
                <span className="feedback-text">{feedbackMsg}</span>
              </div>
              <button
                type="button"
                className="feedback-dismiss-btn"
                onClick={() => setFeedbackMsg('')}
                title="Dismiss message"
              >
                &times;
              </button>
            </div>
          )}
        </section>

        {/* ====================================================================
            3. VISUAL 5-STEP PIPELINE FLOW TRACKER
            ==================================================================== */}
        <section className="pipeline-flow-container">
          {/* STEP 1: SCRAPE */}
          <div
            className={`pipeline-step-node ${activeTab === 'accounts' ? 'selected' : ''}`}
            onClick={() => handleSelectTab('accounts')}
            title="Step 1: Scrapes real company domains matching target niche"
          >
            <div className="node-icon-circle step-1">1</div>
            <div className="node-content">
              <span className="node-step-tag">Step 1</span>
              <span className="node-title">Scrape Accounts</span>
              <span className="node-count">{status.summary.step_1_scraped_accounts} leads found</span>
            </div>
          </div>

          <span className="pipeline-flow-arrow">&rarr;</span>

          {/* STEP 2: FIND COUNT */}
          <div
            className={`pipeline-step-node ${activeTab === 'ready' ? 'selected' : ''}`}
            onClick={() => handleSelectTab('ready')}
            title="Step 2: Audits accounts and prepares uncontacted leads for outreach"
          >
            <div className="node-icon-circle step-2">2</div>
            <div className="node-content">
              <span className="node-step-tag">Step 2</span>
              <span className="node-title">Ready in Queue</span>
              <span className="node-count">{accounts.filter(a => a.status === 'email_found').length} ready to send</span>
            </div>
          </div>

          <span className="pipeline-flow-arrow">&rarr;</span>

          {/* STEP 3: SEND MAILS */}
          <div
            className={`pipeline-step-node ${activeTab === 'sent' ? 'selected' : ''}`}
            onClick={() => handleSelectTab('sent')}
            title="Step 3: Dispatches emails via Hostinger/SMTP and syncs to Sent folder"
          >
            <div className="node-icon-circle step-3">3</div>
            <div className="node-content">
              <span className="node-step-tag">Step 3</span>
              <span className="node-title">Send Mails</span>
              <span className="node-count">{status.summary?.step_3_sent_emails ?? sentOnlyMails.length} sent live</span>
            </div>
          </div>

          <span className="pipeline-flow-arrow">&rarr;</span>


          {/* STEP 4: REPLIES */}
          <div
            className={`pipeline-step-node ${activeTab === 'replies' ? 'selected' : ''}`}
            onClick={() => handleSelectTab('replies')}
            title="Step 4: Scans inbox for prospect replies and updates status"
          >
            <div className="node-icon-circle step-4">4</div>
            <div className="node-content">
              <span className="node-step-tag">Step 4</span>
              <span className="node-title">Find Replies</span>
              <span className="node-count">{status.summary.step_4_replies_found} replies</span>
            </div>
          </div>
        </section>

        {/* ====================================================================
            4. DATA VIEWER PANEL WITH TABS
            ==================================================================== */}
        <section className="data-table-card">
          <div className="table-tabs-header">
            <div className="tabs-group">
              <button
                className={`tab-pill-btn ${activeTab === 'campaigns' ? 'active' : ''}`}
                onClick={() => handleSelectTab('campaigns')}
              >
                <span>Campaigns</span>
                <span className="tab-badge">{campaigns.length}</span>
              </button>

              <button
                className={`tab-pill-btn ${activeTab === 'accounts' ? 'active' : ''}`}
                onClick={() => handleSelectTab('accounts')}
              >
                <span>Scraped Accounts</span>
                <span className="tab-badge">{accounts.length}</span>
              </button>

              <button
                className={`tab-pill-btn ${activeTab === 'ready' ? 'active' : ''}`}
                onClick={() => handleSelectTab('ready')}
              >
                <span>Ready for Outreach</span>
                <span className="tab-badge" style={{ background: '#0284c7', color: '#fff' }}>
                  {accounts.filter(a => a.status === 'email_found').length}
                </span>
              </button>

              <button
                className={`tab-pill-btn ${activeTab === 'sent' ? 'active' : ''}`}
                onClick={() => handleSelectTab('sent')}
              >
                <span>Sent Mails</span>
                <span className="tab-badge" style={{ background: '#059669', color: '#fff' }}>
                  {sentOnlyMails.length}
                </span>
              </button>

              <button
                className={`tab-pill-btn ${activeTab === 'bounced' || activeTab === 'undelivered' ? 'active' : ''}`}
                onClick={() => handleSelectTab('bounced')}
              >
                <span>Bounced Mails</span>
                <span className="tab-badge" style={{ background: '#d97706', color: '#fff' }}>
                  {effectiveBouncedMails.length}
                </span>
              </button>

              <button
                className={`tab-pill-btn ${activeTab === 'blocked' ? 'active' : ''}`}
                onClick={() => handleSelectTab('blocked')}
              >
                <span>Blocked Mails</span>
                <span className="tab-badge" style={{ background: '#dc2626', color: '#fff' }}>
                  {effectiveBlockedMails.length}
                </span>
              </button>

              <button
                className={`tab-pill-btn ${activeTab === 'replies' ? 'active' : ''}`}
                onClick={() => handleSelectTab('replies')}
              >
                <span>Received Replies</span>
                <span className="tab-badge">{replies.length}</span>
              </button>

              <button
                className={`tab-pill-btn ${activeTab === 'runs' ? 'active' : ''}`}
                onClick={() => handleSelectTab('runs')}
              >
                <span>Run Logs</span>
                <span className="tab-badge">{runs.length}</span>
              </button>
            </div>

            <div className="filter-search-box">
              
              <input
                type="text"
                className="filter-search-input"
                placeholder="Filter table rows..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
              {searchQuery && (
                <button
                  type="button"
                  className="filter-search-clear-btn"
                  onClick={() => setSearchQuery('')}
                  title="Clear filter"
                >
                  &times;
                </button>
              )}
            </div>
          </div>

          <div className="table-scroll-area">
            {/* TAB: CAMPAIGNS */}
            {activeTab === 'campaigns' && (
              <div className="campaigns-tab-container">
                {/* Campaigns Summary Header */}
                <div className="campaigns-metrics-banner">
                  <div className="campaign-stat-box created-stat">
                    <span className="stat-label"> Total Campaigns Created</span>
                    <span className="stat-value">{status.summary?.total_campaigns_created ?? campaigns.length}</span>
                    <span className="stat-desc">Distinct campaigns in DataBase</span>
                  </div>

                  <div className="campaign-stat-box run-stat">
                    <span className="stat-label"> Total Campaigns Run</span>
                    <span className="stat-value">{status.summary?.total_campaigns_run ?? 0}</span>
                    <span className="stat-desc">Campaigns executed at least once</span>
                  </div>

                  <div className="campaign-stat-box">
                    <span className="stat-label"> Total Cycles Completed</span>
                    <span className="stat-value">{status.total_runs || campaigns.reduce((acc, c) => acc + (c.total_runs || 0), 0)}</span>
                    <span className="stat-desc"> background automation cycles</span>
                  </div>

                  <div className="campaign-stat-box">
                    <span className="stat-label"> Total Emails Dispatched</span>
                    <span className="stat-value">{status.summary?.step_3_sent_emails || campaigns.reduce((acc, c) => acc + (c.total_emails_sent || 0), 0)}</span>
                    <span className="stat-desc">Emails sent live across all campaigns</span>
                  </div>
                </div>

                {campaigns.length === 0 ? (
                  <div className="no-data-box">
                    <div className="no-data-icon"></div>
                    <h4 className="no-data-title">No Campaigns Created Yet</h4>
                    <p className="no-data-hint">
                      Click <strong>" Create Campaign"</strong> above to define target industries, pitches, and begin outreach.
                    </p>
                    <button
                      className="btn-create-campaign"
                      style={{ marginTop: '16px' }}
                      onClick={() => setIsCampaignModalOpen(true)}
                    >
                       Create First Campaign
                    </button>
                  </div>
                ) : filterRows(campaigns).length === 0 ? (
                  renderNoSearchResults(campaigns.length)
                ) : (
                  <table className="outreach-table campaigns-table">
                    <thead>
                      <tr>
                        <th className="th-num">#</th>
                        <th>Campaign Name</th>
                        <th>Target Query</th>
                        <th>Batch &amp; Interval</th>
                        <th style={{ color: '#38bdf8' }}>Times Run</th>
                        <th>Leads Scraped</th>
                        <th>Emails Sent</th>
                        <th>Replies</th>
                        <th>Last Run</th>
                        <th>Status</th>
                        <th style={{ textAlign: 'right' }}>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filterRows(campaigns).map((camp, idx) => (
                        <tr key={camp.id}>
                          <td className="td-num">{idx + 1}</td>
                          <td>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                              <strong style={{ fontSize: '13.5px', color: '#f8fafc' }}>{camp.name}</strong>
                              {camp.is_active && (
                                <span className="campaign-active-pill" title="This campaign is currently active in the background scheduler">
                                   ACTIVATE CAMPAIGN
                                </span>
                              )}
                            </div>
                          </td>
                          <td style={{ color: '#a5b4fc', fontWeight: 500 }}>{camp.search_query}</td>
                          <td style={{ fontSize: '12px', color: '#cbd5e1' }}>
                            Scrape: {camp.scrape_batch_size} · Send: {camp.send_batch_size} · {camp.interval_seconds}s
                          </td>
                          <td>
                            <span className={`run-count-badge ${camp.total_runs > 0 ? 'has-runs' : 'zero-runs'}`}>
                               {camp.total_runs} {camp.total_runs === 1 ? 'run' : 'runs'}
                            </span>
                          </td>
                          <td style={{ fontWeight: 600, color: '#34d399'   }}>{camp.total_leads_scraped || 0}</td>
                          <td style={{ fontWeight: 600, color: '#60a5fa' }}>{camp.total_emails_sent || 0}</td>
                          <td style={{ fontWeight: 600, color: '#f472b6' }}>{camp.total_replies || 0}</td>
                          <td style={{ fontSize: '12px', color: '#94a3b8' }}>
                            {camp.last_run_at ? formatLocalDateTime(camp.last_run_at) : 'Never'}
                          </td>
                          <td>
                            <span className={`status-chip ${camp.total_runs > 0 ? 'sent' : 'email_found'}`}>
                              {camp.total_runs > 0 ? 'Executed' : 'Ready'}
                            </span>
                          </td>
                          <td>
                            <div className="campaign-row-actions">
                              <button
                                className="btn-camp-action-run"
                                onClick={() => handleRunCampaign(camp.id, camp.name)}
                                title={`Execute a 5-step cycle for "${camp.name}" right now`}
                                disabled={isTriggering}
                              >
                                 Run
                              </button>
                              {!camp.is_active ? (
                                <button
                                  className="btn-camp-action-activate"
                                  onClick={() => handleActivateCampaign(camp.id, camp.name)}
                                  title={`Set "${camp.name}" as the active scheduler campaign`}
                                >
                                   Activate
                                </button>
                              ) : (
                                <span className="camp-active-label">Active</span>
                              )}
                              <button
                                className="btn-camp-action-del"
                                onClick={() => handleDeleteCampaign(camp.id, camp.name)}
                                title={`Delete campaign "${camp.name}"`}
                              >
                                Delete
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            )}
            {/* TAB 1: ACCOUNTS */}
            {activeTab === 'accounts' && (
              accounts.length === 0 ? (
                <div className="no-data-box">
                  <div className="no-data-icon"></div>
                  <h4 className="no-data-title">No Scraped Accounts Yet</h4>
                  <p className="no-data-hint">
                    Click <strong>" Run Cycle Now"</strong> above to scrape verified company mail accounts and dispatch outreach emails automatically.
                  </p>
                  <div style={{ display: 'flex', gap: '10px', marginTop: '14px', justifyContent: 'center' }}>
                    <button
                      className="btn-trigger-now"
                      disabled={isTriggering}
                      onClick={handleTriggerNow}
                    >
                       Run Cycle Now
                    </button>
                  </div>
                </div>
              ) : filterRows(accounts).length === 0 ? (
                renderNoSearchResults(accounts.length)
              ) : (
                <div>
                  <div className="accounts-table-toolbar">
                    <div className="accounts-toolbar-info">
                      <span>Total Accounts: <strong>{accounts.length}</strong></span>
                      <span>•</span>
                      <span>Ready for Outreach: <strong style={{ color: '#38bdf8' }}>{accounts.filter(a => a.status === 'email_found').length}</strong></span>
                      <span>•</span>
                      <span>Contacted: <strong style={{ color: '#34d399' }}>{accounts.filter(a => a.status === 'sent' || a.status === 'replied' || a.status === 'replies').length}</strong></span>
                      {accounts.some(a => a.status === 'bounced') && (
                        <>
                          <span>•</span>
                          <span>Bounced: <strong style={{ color: '#fbbf24' }}>{accounts.filter(a => a.status === 'bounced').length}</strong></span>
                        </>
                      )}
                      {accounts.some(a => a.status === 'blocked_message' || a.status === 'blocked message') && (
                        <>
                          <span>•</span>
                          <span>Blocked: <strong style={{ color: '#f87171' }}>{accounts.filter(a => a.status === 'blocked_message' || a.status === 'blocked message').length}</strong></span>
                        </>
                      )}
                      {accounts.some(a => a.status === 'replies' || a.status === 'replied') && (
                        <>
                          <span>•</span>
                          <span>Replies: <strong style={{ color: '#a78bfa' }}>{accounts.filter(a => a.status === 'replies' || a.status === 'replied').length}</strong></span>
                        </>
                      )}
                    </div>
                  </div>

                  <table className="outreach-table">
                    <thead>
                      <tr>
                        <th className="th-num">#</th>
                        <th>Company</th>
                        <th>Discovered Email</th>
                        <th>Website</th>
                        <th>Industry</th>
                        <th>City</th>
                        <th>Score</th>
                        <th>Status</th>
                        <th>Scraped Date</th>
                        <th style={{ textAlign: 'right' }}>Outreach State</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filterRows(accounts).map((acc, idx) => (
                        <tr key={acc.id} onClick={() => setSelectedRecord({ type: 'account', data: acc })}>
                          <td className="td-num">{idx + 1}</td>
                          <td style={{ fontWeight: 600 }}>{acc.company_name}</td>
                          <td style={{ color: '#60a5fa', fontWeight: 500 }}>{acc.email}</td>
                          <td>
                            <a
                              href={acc.website}
                              target="_blank"
                              rel="noreferrer"
                              style={{ color: '#818cf8', textDecoration: 'none' }}
                              onClick={(e) => e.stopPropagation()}
                            >
                              {acc.website}
                            </a>
                          </td>
                          <td>{acc.industry}</td>
                          <td>{acc.city}</td>
                          <td>{acc.verification_score}/100</td>
                          <td>
                            <span className={`status-chip ${String(acc.status).replace(/\s+/g, '_')}`}>
                              {acc.status === 'blocked_message' || acc.status === 'blocked message' ? 'blocked message' : (acc.status === 'replied' ? 'replies' : acc.status)}
                            </span>
                          </td>
                          <td style={{ color: '#94a3b8' }}>{formatLocalDateTime(acc.scraped_at)}</td>
                          <td style={{ textAlign: 'right' }}>
                            {acc.status === 'email_found' ? (
                              <span style={{ color: '#38bdf8', fontSize: '12px', fontWeight: 600 }}>
                                 In Queue
                              </span>
                            ) : (acc.status === 'blocked_message' || acc.status === 'blocked message') ? (
                              <span style={{ color: '#f87171', fontSize: '12px', fontWeight: 600 }}>
                                 Blocked
                              </span>
                            ) : (acc.status === 'replies' || acc.status === 'replied') ? (
                              <span style={{ color: '#fbbf24', fontSize: '12px', fontWeight: 600 }}>
                                Replies
                              </span>
                            ) : (
                              <span className="text-sent-done">Sent</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )
            )}

            {/* TAB: READY FOR OUTREACH QUEUE (STEP 2 DEDICATED TABLE) */}
            {activeTab === 'ready' && (() => {
              const readyList = accounts.filter(a => a.status === 'email_found')
              const filteredReady = filterRows(readyList)
              return readyList.length === 0 ? (
                <div className="no-data-box">
                  <h4 className="no-data-title">No Accounts in Outreach Queue</h4>
                  <p className="no-data-hint">
                    {accounts.length > 0
                      ? 'All scraped accounts have already been emailed! Click "Run Cycle Now" or enter a new search query to scrape fresh leads.'
                      : 'No mail accounts discovered yet. Click "Run Cycle Now" or enter a search query above to scrape leads.'}
                  </p>
                  <div style={{ display: 'flex', gap: '10px', marginTop: '14px', justifyContent: 'center' }}>
                    <button
                      className="btn-trigger-now"
                      disabled={isTriggering}
                      onClick={handleTriggerNow}
                    >
                       Run Cycle Now to Scrape More Leads
                    </button>
                  </div>
                </div>
              ) : filteredReady.length === 0 ? (
                renderNoSearchResults(readyList.length)
              ) : (
                <div>
                  <div className="accounts-table-toolbar" style={{ borderLeft: '3px solid #38bdf8' }}>
                    <div className="accounts-toolbar-info">
                      <span style={{ color: '#38bdf8', fontWeight: 600 }}>Outreach Queue (Audited Accounts)</span>
                      <span>•</span>
                      <span>Ready to Send: <strong style={{ color: '#38bdf8' }}>{readyList.length}</strong></span>
                      <span>•</span>
                      <span style={{ background: 'rgba(16, 185, 129, 0.15)', color: '#34d399', padding: '2px 8px', borderRadius: '4px', fontSize: '11px', fontWeight: 600, border: '1px solid rgba(16, 185, 129, 0.3)' }}>
                         1 Mail Per Company Enforced
                      </span>
                    </div>
                    <span style={{ fontSize: '12px', color: '#94a3b8', fontWeight: 500 }}>
                       Automatically sent during campaign run
                    </span>
                  </div>

                  <table className="outreach-table">
                    <thead>
                      <tr>
                        <th className="th-num">#</th>
                        <th>Target Company</th>
                        <th>Audited Email</th>
                        <th>Location (City/Country)</th>
                        <th>Website</th>
                        <th>Industry Niche</th>
                        <th>Quality</th>
                        <th>Queue Status</th>
                        <th style={{ textAlign: 'right' }}>Automation Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredReady.map((acc, idx) => (
                        <tr key={acc.id} onClick={() => setSelectedRecord({ type: 'account', data: acc })}>
                          <td className="td-num">{idx + 1}</td>
                          <td style={{ fontWeight: 600, color: '#f8fafc' }}>{acc.company_name}</td>
                          <td style={{ color: '#38bdf8', fontWeight: 600 }}>{acc.email}</td>
                          <td>
                            <span style={{ background: 'rgba(99, 102, 241, 0.15)', color: '#a5b4fc', padding: '3px 8px', borderRadius: '4px', fontSize: '12px' }}>
                              {acc.city || 'Global'}
                            </span>
                          </td>
                          <td>
                            <a
                              href={acc.website}
                              target="_blank"
                              rel="noreferrer"
                              style={{ color: '#818cf8', textDecoration: 'none' }}
                              onClick={(e) => e.stopPropagation()}
                            >
                              {acc.website}
                            </a>
                          </td>
                          <td>{acc.industry}</td>
                          <td>
                            <span style={{ color: '#34d399', fontWeight: 600 }}>
                              {acc.verification_score}/100
                            </span>
                          </td>
                          <td>
                            <span className="status-chip email_found" style={{ background: 'rgba(56, 189, 248, 0.15)', color: '#38bdf8', border: '1px solid rgba(56, 189, 248, 0.3)' }}>
                               Ready for Outreach
                            </span>
                          </td>
                          <td style={{ textAlign: 'right' }}>
                            <span style={{ color: '#38bdf8', fontSize: '12px', fontWeight: 600 }}>
                               Auto-Dispatches in Cycle
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )
            })()}

            {/* TAB 2: SENT MAILS (ONLY SENT MAILS) */}
            {activeTab === 'sent' && (
              sentOnlyMails.length === 0 ? (
                <div className="no-data-box">
                  <div className="no-data-icon"></div>
                  <h4 className="no-data-title">No Sent Emails Yet</h4>
                  <p className="no-data-hint">
                    When the scheduler runs Step 3, it dispatches personalized emails to discovered accounts live via Gmail SMTP.
                  </p>
                </div>
              ) : filterRows(sentOnlyMails).length === 0 ? (
                renderNoSearchResults(sentOnlyMails.length)
              ) : (
                <div>
                  <div className="accounts-table-toolbar" style={{ borderLeft: '3px solid #10b981' }}>
                    <div className="accounts-toolbar-info">
                      <span style={{ color: '#34d399', fontWeight: 600 }}>Sent Mails (Successfully Dispatched)</span>
                      <span>•</span>
                      <span>Total Sent: <strong style={{ color: '#34d399' }}>{sentOnlyMails.length}</strong></span>
                      <span>•</span>
                      <span style={{ fontSize: '12px', color: '#94a3b8' }}>Live SMTP Dispatched &amp; Mailbox Synced</span>
                    </div>
                  </div>

                  <table className="outreach-table">
                    <thead>
                      <tr>
                        <th className="th-num">#</th>
                        <th>Recipient</th>
                        <th>Subject</th>
                        <th>Preview</th>
                        <th>Mode</th>
                        <th>Delivery Status</th>
                        <th>Sent Time</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filterRows(sentOnlyMails).map((m, idx) => (
                        <tr key={m.id} onClick={() => setSelectedRecord({ type: 'sent', data: m })}>
                          <td className="td-num">{idx + 1}</td>
                          <td style={{ fontWeight: 600, color: '#34d399' }}>{m.to_email}</td>
                          <td>{m.subject}</td>
                          <td style={{ color: '#94a3b8', maxWidth: '320px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                            {m.body_snippet}
                          </td>
                          <td>{m.delivery_mode}</td>
                          <td>
                            <span className="status-chip sent">
                              {m.status === 'replied' || m.status === 'replies' ? 'Replied' : 'Sent'}
                            </span>
                          </td>
                          <td style={{ color: '#94a3b8' }}>{formatLocalDateTime(m.sent_at, true)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )
            )}

            {/* TAB 3: BOUNCED MAILS (ONLY BOUNCED RECIPIENTS) */}
            {(activeTab === 'bounced' || activeTab === 'undelivered') && (
              effectiveBouncedMails.length === 0 ? (
                <div className="no-data-box">
                  <div className="no-data-icon"></div>
                  <h4 className="no-data-title">No Bounced Mails Detected</h4>
                  <p className="no-data-hint">
                    Step 4 monitors recipient mailbox delivery failures (such as invalid or non-existent addresses) and automatically suppresses them.
                  </p>
                </div>
              ) : filterRows(effectiveBouncedMails).length === 0 ? (
                renderNoSearchResults(effectiveBouncedMails.length)
              ) : (
                <div>
                  <div className="accounts-table-toolbar" style={{ borderLeft: '3px solid #f59e0b' }}>
                    <div className="accounts-toolbar-info">
                      <span style={{ color: '#fbbf24', fontWeight: 600 }}>Bounced Mails (Invalid Recipient Mailboxes)</span>
                      <span>•</span>
                      <span>Total Bounced: <strong style={{ color: '#fbbf24' }}>{effectiveBouncedMails.length}</strong></span>
                      <span>•</span>
                      <span style={{ fontSize: '12px', color: '#94a3b8' }}>550 Recipient Not Found • Automatically Suppressed</span>
                    </div>
                  </div>

                  <table className="outreach-table">
                    <thead>
                      <tr>
                        <th className="th-num">#</th>
                        <th>Recipient</th>
                        <th>Bounce Diagnostic</th>
                        <th>Error Code</th>
                        <th>Suppression Status</th>
                        <th>Detected Time</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filterRows(effectiveBouncedMails).map((u, idx) => (
                        <tr key={u.id} onClick={() => setSelectedRecord({ type: 'bounced', data: u })}>
                          <td className="td-num">{idx + 1}</td>
                          <td style={{ fontWeight: 600, color: '#fbbf24' }}>{u.to_email}</td>
                          <td style={{ color: '#fde68a' }}>{u.bounce_reason}</td>
                          <td>
                            <span style={{ background: 'rgba(245, 158, 11, 0.15)', color: '#fbbf24', padding: '2px 8px', borderRadius: '4px', fontSize: '12px', fontWeight: 600 }}>
                              {u.error_code || '550'}
                            </span>
                          </td>
                          <td>
                            <span className="status-chip bounced">Permanently Suppressed</span>
                          </td>
                          <td style={{ color: '#94a3b8' }}>{formatLocalDateTime(u.detected_at, true)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )
            )}

            {/* TAB 4: BLOCKED MAILS (ONLY BLOCKED MAILS) */}
            {activeTab === 'blocked' && (
              effectiveBlockedMails.length === 0 ? (
                <div className="no-data-box">
                  <div className="no-data-icon"></div>
                  <h4 className="no-data-title">No Blocked Mails Detected</h4>
                  <p className="no-data-hint">
                    Provider policy blocks (such as Google 554/5.7.1 outbound sending restrictions) are captured and isolated here to protect sender domain reputation.
                  </p>
                </div>
              ) : filterRows(effectiveBlockedMails).length === 0 ? (
                renderNoSearchResults(effectiveBlockedMails.length)
              ) : (
                <div>
                  <div className="accounts-table-toolbar" style={{ borderLeft: '3px solid #ef4444' }}>
                    <div className="accounts-toolbar-info">
                      <span style={{ color: '#f87171', fontWeight: 600 }}>Blocked Mails (Provider Policy Restrictions)</span>
                      <span>•</span>
                      <span>Total Blocked: <strong style={{ color: '#f87171' }}>{effectiveBlockedMails.length}</strong></span>
                      <span>•</span>
                      <span style={{ fontSize: '12px', color: '#94a3b8' }}>554 / 5.7.1 Outbound Sending Restriction • Domain Quarantined</span>
                    </div>
                  </div>

                  <table className="outreach-table">
                    <thead>
                      <tr>
                        <th className="th-num">#</th>
                        <th>Recipient</th>
                        <th>Policy Block Diagnostic</th>
                        <th>Error Code</th>
                        <th>Protection Status</th>
                        <th>Detected Time</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filterRows(effectiveBlockedMails).map((b, idx) => (
                        <tr key={b.id} onClick={() => setSelectedRecord({ type: 'blocked', data: b })}>
                          <td className="td-num">{idx + 1}</td>
                          <td style={{ fontWeight: 600, color: '#f87171' }}>{b.to_email}</td>
                          <td style={{ color: '#fca5a5' }}>{b.bounce_reason}</td>
                          <td>
                            <span style={{ background: 'rgba(239, 68, 68, 0.15)', color: '#f87171', padding: '2px 8px', borderRadius: '4px', fontSize: '12px', fontWeight: 600 }}>
                              {b.error_code || '550 (Blocked)'}
                            </span>
                          </td>
                          <td>
                            <span className="status-chip blocked_message">Policy Blocked</span>
                          </td>
                          <td style={{ color: '#94a3b8' }}>{formatLocalDateTime(b.detected_at, true)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )
            )}

            {/* TAB 4: REPLIES */}
            {activeTab === 'replies' && (
              replies.length === 0 ? (
                <div className="no-data-box">
                  <div className="no-data-icon"></div>
                  <h4 className="no-data-title">No Inbound Replies Yet</h4>
                  <p className="no-data-hint">
                    scans for lead responses and classifies intent (Interested, Meeting Requested, etc.).
                  </p>
                </div>
              ) : filterRows(replies).length === 0 ? (
                renderNoSearchResults(replies.length)
              ) : (
                <table className="outreach-table">
                  <thead>
                    <tr>
                      <th className="th-num">#</th>
                      <th>From</th>
                      <th>Subject</th>
                      <th>Reply Snippet</th>
                      <th>Classification</th>
                      <th>Received Time</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filterRows(replies).map((r, idx) => (
                      <tr key={r.id} onClick={() => setSelectedRecord({ type: 'reply', data: r })}>
                        <td className="td-num">{idx + 1}</td>
                        <td style={{ fontWeight: 600, color: '#fbbf24' }}>{r.from_email}</td>
                        <td>{r.subject}</td>
                        <td style={{ color: '#94a3b8', maxWidth: '300px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                          {r.body}
                        </td>
                        <td>
                          <span className="status-chip replied">{r.sentiment}</span>
                        </td>
                        <td style={{ color: '#94a3b8' }}>{formatLocalDateTime(r.received_at, true)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )
            )}

            {/* TAB 5: RUN HISTORY & LOGS */}
            {activeTab === 'runs' && (
              runs.length === 0 ? (
                <div className="no-data-box">
                  <div className="no-data-icon"></div>
                  <h4 className="no-data-title">No Scheduler Cycles Executed Yet</h4>
                  <p className="no-data-hint">
                    Click <strong>" Run Cycle Now"</strong> to execute Cycle #1.
                  </p>
                </div>
              ) : filterRows(runs).length === 0 ? (
                renderNoSearchResults(runs.length)
              ) : (
                <div>
                  <table className="outreach-table">
                    <thead>
                      <tr>
                        <th className="th-num">#</th>
                        <th>Cycle</th>
                        <th>Campaign</th>
                        <th>Started</th>
                        <th>Completed</th>
                        <th>Scraped</th>
                        <th>Found</th>
                        <th>Sent</th>
                        <th>Undelivered</th>
                        <th>Replies</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filterRows(runs).map((run, idx) => (
                        <tr key={run.id} onClick={() => setSelectedRecord({ type: 'run', data: run })}>
                          <td className="td-num">{idx + 1}</td>
                          <td style={{ fontWeight: 700, color: '#818cf8' }}>Run #{run.run_number}</td>
                          <td style={{ fontWeight: 600, color: '#a5b4fc' }}>{run.campaign_name || 'Default Outreach Campaign'}</td>
                          <td>{formatLocalDateTime(run.started_at, true)}</td>
                          <td>{run.completed_at ? formatLocalDateTime(run.completed_at, true) : 'In progress'}</td>
                          <td>{run.scraped_count}</td>
                          <td>{run.found_count}</td>
                          <td style={{ color: '#34d399' }}>{run.sent_count}</td>
                          <td style={{ color: '#f87171' }}>{run.undelivered_count}</td>
                          <td style={{ color: '#fbbf24' }}>{run.replies_count}</td>
                          <td>
                            <span className="status-chip sent">{run.status}</span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>

                  {runs[0]?.logs && (
                    <div className="logs-terminal">
                      <div style={{ color: '#f8fafc', fontWeight: 700, marginBottom: '8px' }}>
                         Latest Execution Log (Run #{runs[0].run_number}):
                      </div>
                      {runs[0].logs.map((logLine, idx) => (
                        <div key={idx}>{logLine}</div>
                      ))}
                    </div>
                  )}
                </div>
              )
            )}
          </div>
        </section>
      </main>

      {/* ====================================================================
          DETAIL VIEWER MODAL
          ==================================================================== */}
      {selectedRecord && (
        <div className="modal-backdrop-view" onClick={() => setSelectedRecord(null)}>
          <div className="modal-dialog-card" onClick={(e) => e.stopPropagation()}>
            <div className="modal-dialog-header">
              <h3>
                {selectedRecord.type === 'account' && 'Company Mail Account'}
                {selectedRecord.type === 'sent' && 'Sent Outreach Email'}
                {selectedRecord.type === 'bounced' && 'Bounced Mail Diagnostic'}
                {selectedRecord.type === 'blocked' && 'Blocked Mail Policy Diagnostic'}
                {selectedRecord.type === 'undelivered' && 'Undelivered Notice'}
                {selectedRecord.type === 'reply' && 'Lead Reply Message'}
                {selectedRecord.type === 'run' && `Scheduler Cycle #${selectedRecord.data.run_number}`}
              </h3>
              <button className="btn-close-modal-x" onClick={() => setSelectedRecord(null)} title="Close">&times;</button>
            </div>

            <div className="modal-dialog-body">
              {selectedRecord.data.status && (
                <div className="detail-line">
                  <span className="detail-label">Status</span>
                  <span className={`status-chip ${String(selectedRecord.data.status).replace(/\s+/g, '_')}`}>
                    {selectedRecord.data.status === 'blocked_message' || selectedRecord.data.status === 'blocked message' ? 'blocked message' : (selectedRecord.data.status === 'replied' ? 'replies' : selectedRecord.data.status)}
                  </span>
                </div>
              )}

              {selectedRecord.data.company_name && (
                <div className="detail-line">
                  <span className="detail-label">Company Name</span>
                  <span className="detail-value">{selectedRecord.data.company_name}</span>
                </div>
              )}

              {selectedRecord.data.email && (
                <div className="detail-line">
                  <span className="detail-label">Discovered Email</span>
                  <span className="detail-value" style={{ color: '#60a5fa' }}>{selectedRecord.data.email}</span>
                </div>
              )}

              {selectedRecord.data.website && (
                <div className="detail-line">
                  <span className="detail-label">Website</span>
                  <a href={selectedRecord.data.website} target="_blank" rel="noreferrer" style={{ color: '#818cf8' }}>
                    {selectedRecord.data.website}
                  </a>
                </div>
              )}

              {selectedRecord.data.to_email && (
                <div className="detail-line">
                  <span className="detail-label">Recipient</span>
                  <span className="detail-value">{selectedRecord.data.to_email}</span>
                </div>
              )}

              {selectedRecord.data.from_email && (
                <div className="detail-line">
                  <span className="detail-label">Sender</span>
                  <span className="detail-value">{selectedRecord.data.from_email}</span>
                </div>
              )}

              {selectedRecord.data.subject && (
                <div className="detail-line">
                  <span className="detail-label">Subject</span>
                  <span className="detail-value">{selectedRecord.data.subject}</span>
                </div>
              )}

              {selectedRecord.data.sent_at && (
                <div className="detail-line">
                  <span className="detail-label">Sent At (Local)</span>
                  <span className="detail-value">{formatLocalDateTime(selectedRecord.data.sent_at, true)}</span>
                </div>
              )}
              {selectedRecord.data.scraped_at && (
                <div className="detail-line">
                  <span className="detail-label">Scraped At (Local)</span>
                  <span className="detail-value">{formatLocalDateTime(selectedRecord.data.scraped_at, true)}</span>
                </div>
              )}
              {selectedRecord.data.detected_at && (
                <div className="detail-line">
                  <span className="detail-label">Detected At (Local)</span>
                  <span className="detail-value">{formatLocalDateTime(selectedRecord.data.detected_at, true)}</span>
                </div>
              )}
              {selectedRecord.data.received_at && (
                <div className="detail-line">
                  <span className="detail-label">Received At (Local)</span>
                  <span className="detail-value">{formatLocalDateTime(selectedRecord.data.received_at, true)}</span>
                </div>
              )}
              {selectedRecord.data.started_at && (
                <div className="detail-line">
                  <span className="detail-label">Started At (Local)</span>
                  <span className="detail-value">{formatLocalDateTime(selectedRecord.data.started_at, true)}</span>
                </div>
              )}
              {selectedRecord.data.completed_at && (
                <div className="detail-line">
                  <span className="detail-label">Completed At (Local)</span>
                  <span className="detail-value">{formatLocalDateTime(selectedRecord.data.completed_at, true)}</span>
                </div>
              )}

              {selectedRecord.data.bounce_reason && (
                <div className="detail-line">
                  <span className="detail-label">
                    {selectedRecord.type === 'blocked' ? 'Policy Block Diagnostic' : 'Bounce Diagnostic'}
                  </span>
                  <span className="detail-value" style={{ color: selectedRecord.type === 'blocked' ? '#f87171' : '#fbbf24' }}>
                    {selectedRecord.data.bounce_reason}
                  </span>
                </div>
              )}

              {selectedRecord.data.sentiment && (
                <div className="detail-line">
                  <span className="detail-label">AI Intent</span>
                  <span className="detail-value" style={{ color: '#fbbf24' }}>{selectedRecord.data.sentiment}</span>
                </div>
              )}

              {selectedRecord.data.body_snippet && (
                <div className="detail-line">
                  <span className="detail-label">Email Message Body</span>
                  <pre className="detail-pre">{selectedRecord.data.body_snippet}</pre>
                </div>
              )}

              {selectedRecord.data.body && (
                <div className="detail-line">
                  <span className="detail-label">Reply Content</span>
                  <pre className="detail-pre">{selectedRecord.data.body}</pre>
                </div>
              )}

              {selectedRecord.data.logs && (
                <div className="detail-line">
                  <span className="detail-label">Cycle Logs</span>
                  <div className="logs-terminal" style={{ margin: 0 }}>
                    {selectedRecord.data.logs.map((log, i) => (
                      <div key={i}>{log}</div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ====================================================================
          CAMPAIGN CREATION & CONFIGURATION MODAL
          ==================================================================== */}
      {isCampaignModalOpen && (
        <div className="campaign-modal-backdrop" onClick={() => setIsCampaignModalOpen(false)}>
          <div className="campaign-modal-dialog" onClick={(e) => e.stopPropagation()}>
            {/* Header */}
            <div className="campaign-modal-header">
              <div className="campaign-header-left">
                <div className="campaign-icon-badge"></div>
                <div>
                  <h3 className="campaign-modal-title">Create Outreach Campaign</h3>
                  <p className="campaign-modal-subtitle">
                    Automate lead scraping, MX verification, and personalized Gmail outreach
                  </p>
                </div>
              </div>
              <button
                type="button"
                className="campaign-close-x-btn"
                onClick={() => setIsCampaignModalOpen(false)}
                title="Close"
              >
                &times;
              </button>
            </div>

            {/* Scrollable Body */}
            <div className="campaign-modal-body">
              {/* SECTION 1: CAMPAIGN TARGET & QUERY */}
              <div className="campaign-section-card">
                <div className="section-card-title">
                  <span></span>
                  <span>Campaign Target &amp; Industry</span>
                </div>

                <div className="form-group">
                  <label className="form-label">Campaign Title</label>
                  <input
                    type="text"
                    className="campaign-form-input"
                    value={campaignName}
                    onChange={(e) => setCampaignName(e.target.value)}
                    placeholder="Enter campaign title (e.g. Real Estate Outreach)"
                  />
                </div>

                <div className="form-group" style={{ marginTop: '8px' }}>
                  <label className="form-label">Search Query (City, Country, Industry, or Website Domain)</label>
                  <input
                    type="text"
                    className="campaign-form-input"
                    value={editQuery}
                    onChange={(e) => setEditQuery(e.target.value)}
                    placeholder="e.g. IT companies in India, Dentists in Chicago, Real estate in Dubai, Ahmedabad software..."
                  />

                  {/* Quick Preset Pills */}
                  <div className="quick-presets-strip">
                    <span className="presets-label">Popular Targets:</span>
                    {[
                      { label: 'IT in India', query: 'IT companies in India', name: 'India IT Companies Outreach' },
                      { label: 'Dentists in Chicago', query: 'Dentists in Chicago', name: 'Chicago Dentists Outreach' },
                      { label: 'Software in USA', query: 'Software companies in USA', name: 'USA Software Companies Campaign' },
                      { label: 'Real Estate Dubai', query: 'Real estate in Dubai', name: 'Dubai Real Estate Campaign' },
                      { label: 'Ahmedabad Software', query: 'Ahmedabad software companies', name: 'Ahmedabad Tech Outreach' },
                      { label: 'Surat Textile', query: 'Surat textile', name: 'Surat Textile Industry Campaign' },
                      { label: 'Canada Agencies', query: 'Marketing agencies in Canada', name: 'Canada Marketing Agencies Campaign' },
                      { label: 'Medical stores', query: 'Medical stores', name: 'Medical Stores Outreach Campaign' },
                    ].map((preset) => (
                      <button
                        key={preset.query}
                        type="button"
                        className="preset-chip-btn"
                        onClick={() => {
                          setEditQuery(preset.query)
                          setCampaignName(preset.name)
                        }}
                      >
                        {preset.label}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              {/* SECTION 2: AUTOMATION BATCHES & INTERVAL */}
              <div className="campaign-section-card">
                <div className="section-card-title">
                  <span></span>
                  <span>Pipeline Automation Settings</span>
                </div>

                <div className="form-grid-3">
                  <div className="form-group">
                    <label className="form-label">Scrape Count</label>
                    <input
                      type="number"
                      min="0"
                      max="50"
                      className="campaign-form-input"
                      value={editScrapeBatch}
                      onChange={(e) => setEditScrapeBatch(e.target.value === '' ? '' : Math.max(0, parseInt(e.target.value, 10) || 0))}
                      placeholder="e.g. 5"
                    />
                    <span className="field-hint">Leads scraped per cycle</span>
                  </div>

                  <div className="form-group">
                    <label className="form-label">Send Count</label>
                    <input
                      type="number"
                      min="0"
                      max="50"
                      className="campaign-form-input"
                      value={editSendBatch}
                      onChange={(e) => setEditSendBatch(e.target.value === '' ? '' : Math.max(0, parseInt(e.target.value, 10) || 0))}
                      placeholder="e.g. 5"
                    />
                    <span className="field-hint">Emails sent per cycle</span>
                  </div>

                  <div className="form-group">
                    <label className="form-label">Run Interval</label>
                    <select
                      className="campaign-form-input"
                      value={editInterval}
                      onChange={(e) => setEditInterval(e.target.value === '' ? '' : Number(e.target.value))}
                    >
                      <option value="">Select interval...</option>
                      <option value={30}>30 seconds (Fast Test)</option>
                      <option value={60}>1 minute</option>
                      <option value={120}>2 minutes</option>
                      <option value={300}>5 minutes</option>
                      <option value={600}>10 minutes</option>
                      <option value={900}>15 minutes</option>
                      <option value={1800}>30 minutes</option>
                      <option value={3600}>1 hour</option>
                    </select>
                    <span className="field-hint">Time between cycles</span>
                  </div>
                </div>
              </div>

              {/* SECTION 3: PERSONALIZED EMAIL TEMPLATE */}
              <div className="campaign-section-card">
                <div className="section-card-title">
                  <span></span>
                  <span>Personalized Email Pitch</span>
                </div>

                <div className="form-group">
                  <label className="form-label">Email Subject</label>
                  <input
                    type="text"
                    className="campaign-form-input"
                    value={campaignSubject}
                    onChange={(e) => setCampaignSubject(e.target.value)}
                    placeholder="Enter email subject (e.g. Partnership Opportunities for {{company_name}})"
                  />
                </div>

                <div className="form-group" style={{ marginTop: '8px' }}>
                  <label className="form-label">Outreach Message Body</label>
                  <textarea
                    className="campaign-form-input campaign-form-textarea"
                    rows={6}
                    value={campaignBody}
                    onChange={(e) => setCampaignBody(e.target.value)}
                    placeholder="Write your email body template..."
                  />

                  {/* Dynamic Variable Chips */}
                  <div className="template-vars-strip">
                    <span className="vars-label">Click to insert lead variable:</span>
                    <button
                      type="button"
                      className="var-tag-btn"
                      onClick={() => setCampaignBody((prev) => prev + " {{company_name}}")}
                    >
                      + {"{{company_name}}"}
                    </button>
                    <button
                      type="button"
                      className="var-tag-btn"
                      onClick={() => setCampaignBody((prev) => prev + " {{website}}")}
                    >
                      + {"{{website}}"}
                    </button>
                    <button
                      type="button"
                      className="var-tag-btn"
                      onClick={() => setCampaignBody((prev) => prev + " {{industry}}")}
                    >
                      + {"{{industry}}"}
                    </button>
                    <button
                      type="button"
                      className="var-tag-btn"
                      onClick={() => setCampaignBody((prev) => prev + " {{city}}")}
                    >
                      + {"{{city}}"}
                    </button>
                    <button
                      type="button"
                      className="var-tag-btn"
                      onClick={() => setCampaignBody((prev) => prev + " {{sender_name}}")}
                    >
                      + {"{{sender_name}}"}
                    </button>
                  </div>
                </div>

                {/* Sender verification pill */}
                {status.mailbox.email ? (
                  <div className="campaign-sender-note">
                    
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <span>Active Campaign Sender: <strong>{status.mailbox.email}</strong> {status.mailbox.name ? `(${status.mailbox.name})` : ''} · {status.mailbox.smtp_host}</span>
                    </div>
                    <button
                      type="button"
                      className="btn-configure-smtp-pill"
                      onClick={() => { fetchSmtpSettings(); setIsSmtpModalOpen(true); }}
                      title="Edit custom SMTP credentials"
                    >
                       Edit SMTP
                    </button>
                  </div>
                ) : (
                  <div className="campaign-sender-note warning">
                    <span className="sender-note-icon"></span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <span style={{ color: '#fde047', fontWeight: 600 }}>No Sender SMTP Configured! </span>
                      <span style={{ fontSize: '11.5px', color: '#cbd5e1' }}>Set up your email credentials so this campaign can dispatch messages.</span>
                    </div>
                    <button
                      type="button"
                      className="btn-configure-smtp-pill pulse"
                      onClick={() => { fetchSmtpSettings(); setIsSmtpModalOpen(true); }}
                      title="Configure SMTP email credentials"
                    >
                       Set Up SMTP
                    </button>
                  </div>
                )}
              </div>
            </div>

            {/* Footer Actions */}
            <div className="campaign-modal-footer">
              <div className="footer-right-actions">
                <button
                  type="button"
                  className="btn-campaign-cancel"
                  onClick={() => setIsCampaignModalOpen(false)}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  className="btn-campaign-save-only"
                  onClick={handleSaveCampaignOnly}
                  title="Save campaign to database without starting scheduler"
                >
                   Save Standby
                </button>
                <button
                  type="button"
                  className="btn-campaign-schedule"
                  onClick={handleSaveAndStartScheduler}
                  title="Save configuration and start periodic background schedule"
                >
                   Save &amp; Start Scheduler
                </button>
                <button
                  type="button"
                  className="btn-campaign-launch"
                  onClick={handleLaunchCampaign}
                  title="Save configuration and immediately run a 5-step cycle right now"
                >
                   Launch &amp; Run Now
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ====================================================================
          MAIL EDITOR & TEMPLATE CUSTOMIZATION MODAL
          ==================================================================== */}
      {isMailEditorOpen && (
        <div className="campaign-modal-backdrop" onClick={() => setIsMailEditorOpen(false)}>
          <div className="campaign-modal-dialog mail-editor-dialog" onClick={(e) => e.stopPropagation()}>
            {/* Header */}
            <div className="campaign-modal-header" style={{ background: 'linear-gradient(180deg, #1e1b4b, #0f172a)' }}>
              <div className="campaign-header-left">
                <div className="campaign-icon-badge" style={{ background: 'linear-gradient(135deg, #6366f1, #a855f7)', color: '#fff' }}>
                  
                </div>
                <div>
                  <h3 className="campaign-modal-title">Mail Editor</h3>
                  <p className="campaign-modal-subtitle">
                    Customize the exact email subject, body message, and variable tags sent to companies.
                  </p>
                </div>
              </div>
              <button
                type="button"
                className="campaign-close-x-btn"
                onClick={() => setIsMailEditorOpen(false)}
                title="Close"
              >
                &times;
              </button>
            </div>

            {/* Body */}
            <div className="campaign-modal-body">
              {/* Presets Strip */}
              <div>
                <span style={{ fontSize: '12px', fontWeight: 600, color: '#94a3b8', display: 'block', marginBottom: '8px' }}>
                   Quick Load Proven Templates:
                </span>
                <div className="template-presets-grid">
                  {MAIL_PRESETS.map((preset) => (
                    <button
                      key={preset.label}
                      type="button"
                      className="preset-template-btn"
                      onClick={() => {
                        setEditorSubject(preset.subject)
                        setEditorBody(preset.body)
                      }}
                      title="Load this template into editor"
                    >
                      {preset.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Two Column Grid: Editor (Left) & Live Preview (Right) */}
              <div className="mail-editor-grid">
                {/* LEFT: EDIT PANE */}
                <div className="editor-pane">
                  <div className="pane-section-title">
                    <span>Edit Email Template</span>
                  </div>

                  {/* Subject Line */}
                  <div className="form-group">
                    <label className="form-label">Email Subject Line</label>
                    <input
                      type="text"
                      className="campaign-form-input"
                      value={editorSubject}
                      onChange={(e) => setEditorSubject(e.target.value)}
                      placeholder="Enter email subject (e.g. Partnership Opportunities for {{company_name}})"
                    />
                  </div>

                  {/* React Rich Text Editor Component for Email Body */}
                  <div className="form-group" style={{ marginBottom: '14px' }}>
                    <label className="form-label">Email Message Body</label>
                    <RichTextEditor
                      value={editorBody}
                      onChange={setEditorBody}
                      placeholder="Compose your outreach message body..."
                      minHeight="260px"
                    />
                  </div>

                  {/* AI Enhancement Toolbar */}
                  <div className="ai-enhance-bar">
                    <div className="ai-enhance-controls">
                      <span style={{ fontSize: '12px', fontWeight: 600, color: '#e2e8f0' }}>AI Polisher:</span>
                      <select
                        className="ai-tone-select"
                        value={enhanceTone}
                        onChange={(e) => setEnhanceTone(e.target.value)}
                      >
                        <option value="persuasive">Persuasive (High Conversion)</option>
                        <option value="professional">Professional & Formal</option>
                        <option value="friendly">Friendly & Casual</option>
                        <option value="short and concise">Short & Direct (under 60 words)</option>
                      </select>
                    </div>
                    <button
                      type="button"
                      className="btn-ai-enhance"
                      disabled={isEnhancing}
                      onClick={handleEnhanceMailTemplate}
                      title="Use Groq LLM to polish and upgrade your copy"
                    >
                      {isEnhancing ? ' Enhancing...' : 'Polish with AI'}
                    </button>
                  </div>
                </div>

                {/* RIGHT: LIVE RECIPIENT PREVIEW */}
                <div className="preview-pane">
                  <div className="pane-section-title">
                    <span>Live Recipient View</span>
                  </div>

                  <div className="email-client-card">
                    <div className="email-client-header">
                      <div className="window-dots">
                        <span className="dot red"></span>
                        <span className="dot yellow"></span>
                        <span className="dot green"></span>
                      </div>
                      <span style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 600 }}>Simulated Recipient Inbox</span>
                    </div>

                    <div className="email-meta-strip">
                      <div className="email-meta-line">
                        <span className="meta-label">From:</span>
                        <span className="meta-value" style={{ color: '#38bdf8' }}>
                          {status.mailbox?.name ? `${status.mailbox.name} <${status.mailbox.email}>` : (status.mailbox?.email || 'chovatiyajanki1913@gmail.com')}
                        </span>
                      </div>
                      <div className="email-meta-line">
                        <span className="meta-label">To:</span>
                        <span className="meta-value">contact@apexinnovate.com (Lead)</span>
                      </div>
                      <div className="email-meta-line">
                        <span className="meta-label">Subject:</span>
                        <span className="meta-subject">
                          {renderLivePreview(editorSubject, false) || '(No subject entered)'}
                        </span>
                      </div>
                    </div>

                    <div
                      className="email-body-preview"
                      dangerouslySetInnerHTML={{
                        __html: renderLivePreview(editorBody, true) || '<span style="color:#64748b;">Start typing in the editor on the left to see your email rendered here in real time...</span>'
                      }}
                    />

                    <div style={{ padding: '10px 16px', background: '#080d19', borderTop: '1px solid #1e293b', fontSize: '11.5px', color: '#94a3b8' }}>
                       <strong>Live Test Sample:</strong> Variables like <code>{"{{company_name}}"}</code>, <code>{"{{city}}"}</code>, <code>{"{{website}}"}</code> are automatically substituted with each target company's real data upon dispatch.
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* Footer */}
            <div className="campaign-modal-footer">
              <button
                type="button"
                className="btn-campaign-cancel campaign-cancel-btn"
                onClick={() => setIsMailEditorOpen(false)}
              >
                Cancel
              </button>
              <div className="footer-right-actions">
                <button
                  type="button"
                  className="btn-campaign-save-only"
                  onClick={() => {
                    setEditorSubject('')
                    setEditorBody('')
                  }}
                >
                  Clear Template
                </button>
                <button
                  type="button"
                  className="btn-campaign-launch"
                  style={{ background: 'linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%)' }}
                  disabled={isSavingTemplate}
                  onClick={handleSaveMailTemplate}
                >
                  {isSavingTemplate ? 'Saving...' : 'Save & Apply Template'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ====================================================================
          SMTP CONFIGURATION MODAL (MANUAL SMTP SETTINGS)
          ==================================================================== */}
      {isSmtpModalOpen && (
        <div className="campaign-modal-backdrop" onClick={() => setIsSmtpModalOpen(false)}>
          <div className="campaign-modal-dialog smtp-modal-dialog" onClick={(e) => e.stopPropagation()}>
            {/* Header */}
            <div className="campaign-modal-header">
              <div className="campaign-header-left">
                <div className="campaign-icon-badge smtp-icon-badge"></div>
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <h3 className="campaign-modal-title">SMTP Mail Server Settings</h3>
                  </div>
                  <p className="campaign-modal-subtitle">
                    Configure your manual SMTP mail server (Gmail, Office 365, Amazon SES, SendGrid, or custom SMTP).
                  </p>
                </div>
              </div>
              <button
                type="button"
                className="campaign-close-x-btn"
                onClick={() => setIsSmtpModalOpen(false)}
                title="Close"
              >
                &times;
              </button>
            </div>

            {/* Body */}
            <div className="campaign-modal-body">
              {/* Presets Strip */}
              <div className="smtp-presets-card">
                <span className="smtp-presets-label"> Quick Presets:</span>
                <div className="smtp-presets-list">
                  <button
                    type="button"
                    className={`smtp-preset-chip hostinger-preset ${smtpHost === 'smtp.hostinger.com' && Number(smtpPort) === 465 ? 'active' : ''}`}
                    onClick={() => applySmtpPreset('hostinger')}
                    style={{ borderColor: 'rgba(168, 85, 247, 0.45)', color: '#d8b4fe', fontWeight: 700 }}
                    title="Hostinger Mail with SSL (Port 465 - Recommended by Hostinger)"
                  >
                    Hostinger Mail (SSL 465)
                  </button>
                  <button
                    type="button"
                    className={`smtp-preset-chip hostinger-preset ${smtpHost === 'smtp.hostinger.com' && Number(smtpPort) === 587 ? 'active' : ''}`}
                    onClick={() => applySmtpPreset('hostinger_tls')}
                    style={{ borderColor: 'rgba(168, 85, 247, 0.45)', color: '#d8b4fe' }}
                    title="Hostinger Mail with STARTTLS (Port 587)"
                  >
                    Hostinger Mail (TLS 587)
                  </button>
                  <button
                    type="button"
                    className={`smtp-preset-chip ${smtpHost === 'smtp.gmail.com' && Number(smtpPort) === 587 ? 'active' : ''}`}
                    onClick={() => applySmtpPreset('gmail')}
                  >
                    Gmail (TLS 587)
                  </button>
                  <button
                    type="button"
                    className={`smtp-preset-chip ${smtpHost === 'smtp.gmail.com' && Number(smtpPort) === 465 ? 'active' : ''}`}
                    onClick={() => applySmtpPreset('gmail_ssl')}
                  >
                    Gmail (SSL 465)
                  </button>
                  <button
                    type="button"
                    className={`smtp-preset-chip ${smtpHost === 'smtp.office365.com' ? 'active' : ''}`}
                    onClick={() => applySmtpPreset('office365')}
                  >
                    Office 365 (587)
                  </button>
                  <button
                    type="button"
                    className={`smtp-preset-chip ${smtpHost === 'smtp.mail.yahoo.com' ? 'active' : ''}`}
                    onClick={() => applySmtpPreset('yahoo')}
                  >
                    Yahoo Mail (587)
                  </button>
                  <button
                    type="button"
                    className={`smtp-preset-chip ${smtpHost === 'smtp.sendgrid.net' ? 'active' : ''}`}
                    onClick={() => applySmtpPreset('sendgrid')}
                  >
                    SendGrid (587)
                  </button>
                </div>
              </div>

              {/* Server & Port Row */}
              <div className="campaign-section-card">
                <div className="section-card-title">
                  <span></span>
                  <span>Server Connection</span>
                </div>

                <div className="campaign-grid-2">
                  <div className="form-group">
                    <label className="form-label">SMTP Hostname <span className="field-required">*</span></label>
                    <input
                      type="text"
                      className="campaign-form-input"
                      value={smtpHost}
                      onChange={(e) => { setSmtpHost(e.target.value); setSmtpTestResult(null); }}
                      placeholder="e.g. smtp.hostinger.com or smtp.gmail.com"
                    />
                    <span className="field-hint">Hostinger: smtp.hostinger.com | Gmail: smtp.gmail.com</span>
                  </div>

                  <div className="form-group">
                    <label className="form-label">Port Number <span className="field-required">*</span></label>
                    <input
                      type="number"
                      className="campaign-form-input"
                      value={smtpPort}
                      onChange={(e) => { setSmtpPort(Number(e.target.value)); setSmtpTestResult(null); }}
                      placeholder="465 or 587"
                    />
                    <span className="field-hint">465 (SSL - Hostinger Recommended) or 587 (TLS)</span>
                  </div>
                </div>
              </div>

              {/* Authentication Credentials Row */}
              <div className="campaign-section-card">
                <div className="section-card-title">
                  <span></span>
                  <span>Authentication Credentials</span>
                </div>

                <div className="campaign-grid-2">
                  <div className="form-group">
                    <label className="form-label">Username / Email Address <span className="field-required">*</span></label>
                    <input
                      type="text"
                      className="campaign-form-input"
                      value={smtpUsername}
                      onChange={(e) => { setSmtpUsername(e.target.value); setSmtpTestResult(null); }}
                      placeholder="e.g. info@yourdomain.com (Full email)"
                    />
                    <span className="field-hint">For Hostinger, enter your full email address</span>
                  </div>

                  <div className="form-group">
                    <label className="form-label">Password / App Password <span className="field-required">*</span></label>
                    <div className="password-input-group">
                      <input
                        type={showSmtpPassword ? 'text' : 'password'}
                        className="campaign-form-input"
                        value={smtpPassword}
                        onChange={(e) => { setSmtpPassword(e.target.value); setSmtpTestResult(null); }}
                        placeholder="Hostinger mailbox password or Gmail App Password"
                      />
                      <button
                        type="button"
                        className="btn-toggle-eye"
                        onClick={() => setShowSmtpPassword(!showSmtpPassword)}
                        title={showSmtpPassword ? 'Hide password' : 'Show password'}
                      >
                        {showSmtpPassword ? 'Hide' : 'Show'}
                      </button>
                    </div>
                    <span className="field-hint">Hostinger Webmail password or 16-char Gmail App Password</span>
                  </div>
                </div>

                <div className="form-group" style={{ marginTop: '12px' }}>
                  <label className="form-label">Sender Display Name</label>
                  <input
                    type="text"
                    className="campaign-form-input"
                    value={smtpSenderName}
                    onChange={(e) => setSmtpSenderName(e.target.value)}
                    placeholder="e.g. Sales Team or Your Name"
                  />
                  <span className="field-hint">Display name shown to recipients in their email inbox</span>
                </div>

                {/* Helpful Note for Hostinger Users */}
                <div className="smtp-info-box" style={{ background: 'rgba(168, 85, 247, 0.12)', border: '1px solid rgba(168, 85, 247, 0.35)', color: '#e9d5ff', marginTop: '10px' }}>
                  
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
                    <span style={{ fontWeight: 700, color: '#f3e8ff' }}>Hostinger Mail Configuration:</span>
                    <span style={{ fontSize: '11.5px', lineHeight: 1.5, color: '#d8b4fe' }}>
                      • <strong>SMTP Server:</strong> <code>smtp.hostinger.com</code> | <strong>Port:</strong> <code>465</code> (SSL) or <code>587</code> (TLS)<br/>
                      • <strong>IMAP Server (for replies):</strong> <code>imap.hostinger.com</code>:<code>993</code> (auto-configured)<br/>
                      • <strong>Username:</strong> Your full Hostinger email address (e.g. <code>info@yourdomain.com</code>)<br/>
                      • <strong>Password:</strong> Your Hostinger mailbox password (<a href="https://mail.hostinger.com" target="_blank" rel="noreferrer" style={{ color: '#c084fc', textDecoration: 'underline' }}>Hostinger Webmail</a> login)
                    </span>
                  </div>
                </div>

                {/* Helpful Note for Gmail Users */}
                <div className="smtp-info-box" style={{ marginTop: '8px' }}>
                  
                  <span>
                    <strong>Gmail Notice:</strong> If using Gmail with 2-Step Verification, generate a 16-character
                    <strong> App Password</strong> at <code>myaccount.google.com/apppasswords</code>.
                  </span>
                </div>
              </div>

              {/* Test Connection Result Box */}
              {smtpTesting && (
                <div className="smtp-test-status loading">
                  
                  <span>Connecting to {smtpHost}:{smtpPort} and verifying credentials...</span>
                </div>
              )}

              {smtpTestResult && !smtpTesting && (
                <div className={`smtp-test-status ${smtpTestResult.success ? 'success' : 'error'}`}>
                  <span>{smtpTestResult.success ? '[OK] ' : '[Error] '}</span>
                  <span>{smtpTestResult.message}</span>
                </div>
              )}
            </div>

            {/* Modal Footer */}
            <div className="campaign-modal-footer">
              <div className="footer-left-status" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <button
                  type="button"
                  className="btn-smtp-test"
                  onClick={handleTestSmtp}
                  disabled={smtpTesting || !smtpHost || !smtpUsername || !smtpPassword}
                  title="Test authentication without saving"
                >
                  {smtpTesting ? ' Testing...' : ' Test Connection'}
                </button>

                {(status.mailbox.email || smtpUsername) && (
                  <button
                    type="button"
                    className="btn-smtp-remove"
                    onClick={handleRemoveSmtp}
                    title="Remove and reset saved SMTP credentials"
                  >
                     Remove Settings
                  </button>
                )}
              </div>

              <div className="footer-right-actions">
                <button
                  type="button"
                  className="btn-campaign-cancel"
                  onClick={() => setIsSmtpModalOpen(false)}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  className="btn-campaign-launch"
                  onClick={handleSaveSmtp}
                  disabled={smtpSaving || !smtpHost || !smtpUsername || !smtpPassword}
                  title="Save manual SMTP credentials to DataBase for future campaigns"
                >
                  {smtpSaving ? 'Saving...' : ' Save SMTP Settings'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

    </div>
  )
}
