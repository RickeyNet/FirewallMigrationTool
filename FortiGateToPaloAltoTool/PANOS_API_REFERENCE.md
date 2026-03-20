# PAN-OS XML API Reference

Comprehensive reference for the Palo Alto Networks PAN-OS XML API, targeting PA-440 and compatible devices running PAN-OS 10.1+.

---

## Table of Contents

1. [Authentication](#authentication)
2. [API Request Format](#api-request-format)
3. [Configuration Actions](#configuration-actions)
4. [XPath Reference](#xpath-reference)
5. [XML Element Payloads](#xml-element-payloads)
6. [Commit & Job Monitoring](#commit--job-monitoring)
7. [Naming Rules](#naming-rules)
8. [PA-440 Hardware Reference](#pa-440-hardware-reference)
9. [Error Handling](#error-handling)
10. [Rate Limiting & Best Practices](#rate-limiting--best-practices)

---

## Authentication

### Generate API Key

```
POST https://<firewall>/api/?type=keygen
Content-Type: application/x-www-form-urlencoded
Body: user=<username>&password=<password>
```

**Response (success):**
```xml
<response status="success">
  <result>
    <key>LUFRPT1BbWtMNGRKMUFwODNJUU9mUmFMbXBMaUF...</key>
  </result>
</response>
```

**Response (failure):**
```xml
<response status="error">
  <result>
    <msg>Invalid credentials</msg>
  </result>
</response>
```

### Using the API Key

**Option 1 — HTTP Header (recommended):**
```
X-PAN-KEY: <api_key>
```

**Option 2 — URL Parameter:**
```
https://<firewall>/api/?type=config&action=get&xpath=...&key=<api_key>
```

### Key Behavior
- Keys do not expire by default (configurable under Device > Setup > Management > Authentication Settings)
- Generating a new key for the same user invalidates all previous keys and sessions
- Keys are tied to the user's role and permissions

---

## API Request Format

### Base URL
```
https://<firewall>/api/
```

### Common Parameters

| Parameter | Description |
|-----------|-------------|
| `type` | Request type: `keygen`, `config`, `commit`, `op`, `report`, `log` |
| `action` | Config action: `get`, `show`, `set`, `edit`, `delete`, `rename`, `clone`, `move` |
| `xpath` | XPath to target configuration node |
| `element` | XML element to set/edit (URL-encoded) |
| `key` | API key (or use `X-PAN-KEY` header) |

### Example Request
```
POST https://<fw>/api/?type=config&action=set&xpath=/config/devices/entry[@name='localhost.localdomain']/vsys/entry[@name='vsys1']/address&element=<entry name="test"><ip-netmask>10.0.0.1/32</ip-netmask></entry>&key=<key>
```

---

## Configuration Actions

### `set` — Create or Merge
Adds new entries or merges into existing configuration. **Idempotent** for new objects.
- If the entry already exists, `set` merges the provided XML into the existing entry
- If the entry does not exist, it is created
- Does NOT delete children not specified in the element

### `edit` — Replace Entire Node
Replaces the entire node at the given XPath with the provided element.
- **Destructive**: removes any children not included in the new element
- XPath must point to a specific entry: `...address/entry[@name='test']`
- Element must include the full node (including `<entry name="...">`)

### `get` — Read Candidate Configuration
Returns the candidate (uncommitted) configuration at the specified XPath.
```
GET https://<fw>/api/?type=config&action=get&xpath=<xpath>&key=<key>
```

### `show` — Read Running Configuration
Returns the active (committed) running configuration.
```
GET https://<fw>/api/?type=config&action=show&xpath=<xpath>&key=<key>
```

### `delete` — Remove Configuration
Removes the entry at the specified XPath.
```
POST https://<fw>/api/?type=config&action=delete&xpath=<xpath>/entry[@name='object_name']&key=<key>
```

### `rename` — Rename Object
```
POST https://<fw>/api/?type=config&action=rename&xpath=<xpath>/entry[@name='old']&newname=new&key=<key>
```

---

## XPath Reference

All XPaths below assume a standalone firewall with vsys1 (default for PA-440).

### Base Prefix
```
/config/devices/entry[@name='localhost.localdomain']
```

### Object XPaths

| Object Type | XPath (relative to base prefix) |
|---|---|
| **Address objects** | `/vsys/entry[@name='vsys1']/address` |
| **Address groups** | `/vsys/entry[@name='vsys1']/address-group` |
| **Service objects** | `/vsys/entry[@name='vsys1']/service` |
| **Service groups** | `/vsys/entry[@name='vsys1']/service-group` |
| **Security rules** | `/vsys/entry[@name='vsys1']/rulebase/security/rules` |
| **NAT rules** | `/vsys/entry[@name='vsys1']/rulebase/nat/rules` |
| **Zones** | `/vsys/entry[@name='vsys1']/zone` |
| **Tags** | `/vsys/entry[@name='vsys1']/tag` |

### Network XPaths (outside vsys)

| Object Type | XPath (relative to base prefix) |
|---|---|
| **Ethernet interfaces** | `/network/interface/ethernet` |
| **Loopback interfaces** | `/network/interface/loopback` |
| **Tunnel interfaces** | `/network/interface/tunnel` |
| **Virtual routers** | `/network/virtual-router` |
| **Static routes** | `/network/virtual-router/entry[@name='default']/routing-table/ip/static-route` |
| **DNS proxy** | `/network/dns-proxy` |

### Targeting Specific Entries
Append `/entry[@name='object_name']` to any XPath to target a specific object:
```
/vsys/entry[@name='vsys1']/address/entry[@name='webserver']
```

### Full XPath Examples

**All address objects:**
```
/config/devices/entry[@name='localhost.localdomain']/vsys/entry[@name='vsys1']/address
```

**Specific address object:**
```
/config/devices/entry[@name='localhost.localdomain']/vsys/entry[@name='vsys1']/address/entry[@name='webserver']
```

**All security rules:**
```
/config/devices/entry[@name='localhost.localdomain']/vsys/entry[@name='vsys1']/rulebase/security/rules
```

---

## XML Element Payloads

### Address Objects

**Host (ip-netmask):**
```xml
<entry name="webserver">
  <ip-netmask>10.10.20.100/32</ip-netmask>
  <description>Web server</description>
  <tag>
    <member>Migrated</member>
  </tag>
</entry>
```

**Subnet (ip-netmask):**
```xml
<entry name="server_subnet">
  <ip-netmask>10.10.20.0/24</ip-netmask>
  <description>Server subnet</description>
</entry>
```

**Range (ip-range):**
```xml
<entry name="dhcp_pool">
  <ip-range>10.0.0.100-10.0.0.200</ip-range>
  <description>DHCP pool range</description>
</entry>
```

**FQDN:**
```xml
<entry name="google_dns">
  <fqdn>dns.google</fqdn>
  <description>Google DNS</description>
</entry>
```

### Address Groups

**Static group:**
```xml
<entry name="web_servers">
  <static>
    <member>webserver1</member>
    <member>webserver2</member>
    <member>webserver3</member>
  </static>
  <description>All web servers</description>
</entry>
```

**Dynamic group (tag-based):**
```xml
<entry name="cloud_servers">
  <dynamic>
    <filter>'cloud' and 'production'</filter>
  </dynamic>
</entry>
```

**Nested group (supported natively):**
```xml
<entry name="all_servers">
  <static>
    <member>web_servers</member>
    <member>db_servers</member>
    <member>standalone_host</member>
  </static>
</entry>
```

### Service Objects

**TCP service (single port):**
```xml
<entry name="tcp_8080">
  <protocol>
    <tcp>
      <port>8080</port>
    </tcp>
  </protocol>
  <description>Custom HTTP port</description>
</entry>
```

**TCP service (port range):**
```xml
<entry name="tcp_high_ports">
  <protocol>
    <tcp>
      <port>8000-8999</port>
    </tcp>
  </protocol>
</entry>
```

**TCP service (source port specified):**
```xml
<entry name="tcp_with_src">
  <protocol>
    <tcp>
      <port>443</port>
      <source-port>1024-65535</source-port>
    </tcp>
  </protocol>
</entry>
```

**UDP service:**
```xml
<entry name="udp_5060">
  <protocol>
    <udp>
      <port>5060</port>
    </udp>
  </protocol>
  <description>SIP</description>
</entry>
```

**Note:** PAN-OS service objects support only ONE protocol per object (tcp OR udp, not both). FortiGate services with both TCP and UDP ports must be split into two PAN-OS service objects.

### Service Groups

```xml
<entry name="web_services">
  <members>
    <member>tcp_80</member>
    <member>tcp_443</member>
    <member>tcp_8080</member>
  </members>
</entry>
```

**Note:** Service groups can contain both service objects AND other service groups (nesting supported).

### Security Rules

**Basic allow rule:**
```xml
<entry name="Allow_Web_Traffic">
  <from>
    <member>untrust</member>
  </from>
  <to>
    <member>trust</member>
  </to>
  <source>
    <member>any</member>
  </source>
  <destination>
    <member>webserver</member>
    <member>web_servers</member>
  </destination>
  <service>
    <member>tcp_80</member>
    <member>tcp_443</member>
  </service>
  <application>
    <member>any</member>
  </application>
  <action>allow</action>
  <log-start>no</log-start>
  <log-end>yes</log-end>
  <log-setting>default</log-setting>
  <description>Allow inbound web traffic</description>
  <disabled>no</disabled>
</entry>
```

**Deny rule:**
```xml
<entry name="Deny_All">
  <from>
    <member>any</member>
  </from>
  <to>
    <member>any</member>
  </to>
  <source>
    <member>any</member>
  </source>
  <destination>
    <member>any</member>
  </destination>
  <service>
    <member>any</member>
  </service>
  <application>
    <member>any</member>
  </application>
  <action>deny</action>
  <log-end>yes</log-end>
</entry>
```

**Multi-zone rule:**
```xml
<entry name="Cross_Zone">
  <from>
    <member>trust</member>
    <member>dmz</member>
  </from>
  <to>
    <member>untrust</member>
  </to>
  <source>
    <member>internal_networks</member>
  </source>
  <destination>
    <member>any</member>
  </destination>
  <service>
    <member>application-default</member>
  </service>
  <application>
    <member>ssl</member>
    <member>web-browsing</member>
  </application>
  <action>allow</action>
</entry>
```

### Security Rule Fields Reference

| Field | Required | Values | Default |
|---|---|---|---|
| `<from>` | Yes | Zone names or `any` | — |
| `<to>` | Yes | Zone names or `any` | — |
| `<source>` | Yes | Address/group names or `any` | — |
| `<destination>` | Yes | Address/group names or `any` | — |
| `<service>` | Yes | Service/group names, `any`, or `application-default` | — |
| `<application>` | Yes | App names or `any` | — |
| `<action>` | Yes | `allow`, `deny`, `drop`, `reset-client`, `reset-server`, `reset-both` | — |
| `<log-start>` | No | `yes`, `no` | `no` |
| `<log-end>` | No | `yes`, `no` | `no` |
| `<log-setting>` | No | Log forwarding profile name or `default` | — |
| `<description>` | No | Text (max 1023 chars) | — |
| `<disabled>` | No | `yes`, `no` | `no` |
| `<tag>` | No | `<member>tag_name</member>` | — |
| `<negate-source>` | No | `yes`, `no` | `no` |
| `<negate-destination>` | No | `yes`, `no` | `no` |

### Static Routes

**Standard route with gateway:**
```xml
<entry name="route_to_10">
  <destination>10.0.0.0/8</destination>
  <nexthop>
    <ip-address>192.168.1.1</ip-address>
  </nexthop>
  <interface>ethernet1/1</interface>
  <metric>10</metric>
</entry>
```

**Default route:**
```xml
<entry name="default_route">
  <destination>0.0.0.0/0</destination>
  <nexthop>
    <ip-address>203.0.113.1</ip-address>
  </nexthop>
  <interface>ethernet1/1</interface>
  <metric>10</metric>
</entry>
```

**Route without interface (nexthop only):**
```xml
<entry name="remote_route">
  <destination>172.16.0.0/12</destination>
  <nexthop>
    <ip-address>10.0.0.1</ip-address>
  </nexthop>
  <metric>100</metric>
</entry>
```

**Discard route (blackhole equivalent):**
```xml
<entry name="blackhole">
  <destination>192.168.99.0/24</destination>
  <nexthop>
    <discard/>
  </nexthop>
</entry>
```

### Zones

**Layer 3 zone:**
```xml
<entry name="trust">
  <network>
    <layer3>
      <member>ethernet1/1</member>
      <member>ethernet1/2</member>
    </layer3>
  </network>
</entry>
```

**Layer 2 zone:**
```xml
<entry name="l2_zone">
  <network>
    <layer2>
      <member>ethernet1/3</member>
    </layer2>
  </network>
</entry>
```

### Interfaces (Ethernet)

**Layer 3 interface:**
```xml
<entry name="ethernet1/1">
  <layer3>
    <ip>
      <entry name="10.0.1.1/24"/>
    </ip>
    <mtu>1500</mtu>
  </layer3>
  <comment>Inside interface</comment>
</entry>
```

**Subinterface (VLAN):**
```xml
<entry name="ethernet1/1.100">
  <tag>100</tag>
  <ip>
    <entry name="10.100.0.1/24"/>
  </ip>
  <comment>VLAN 100</comment>
</entry>
```
XPath for subinterfaces:
```
/config/devices/entry[@name='localhost.localdomain']/network/interface/ethernet/entry[@name='ethernet1/1']/layer3/units
```

---

## Commit & Job Monitoring

### Commit All Changes
```
POST https://<fw>/api/?type=commit&cmd=<commit></commit>&key=<key>
```

**Response (commit enqueued):**
```xml
<response status="success" code="19">
  <result>
    <msg>
      <line>Commit job enqueued with jobid 152</line>
    </msg>
    <job>152</job>
  </result>
</response>
```

**Response (nothing to commit):**
```xml
<response status="success" code="13">
  <result>
    <msg>
      <line>There are no changes to commit.</line>
    </msg>
  </result>
</response>
```

### Partial Commit (admin-level)
```
POST https://<fw>/api/?type=commit&cmd=<commit><partial><admin><member>admin_username</member></admin></partial></commit>&key=<key>
```

### Force Commit
```
POST https://<fw>/api/?type=commit&cmd=<commit><force></force></commit>&key=<key>
```

### Check Job Status
```
GET https://<fw>/api/?type=op&cmd=<show><jobs><id>152</id></jobs></show>&key=<key>
```

**Response (in progress):**
```xml
<response status="success">
  <result>
    <job>
      <id>152</id>
      <status>ACT</status>
      <result>PEND</result>
      <progress>45</progress>
      <details><line>Configuration committed partially</line></details>
    </job>
  </result>
</response>
```

**Response (completed):**
```xml
<response status="success">
  <result>
    <job>
      <id>152</id>
      <status>FIN</status>
      <result>OK</result>
      <progress>100</progress>
      <details><line>Configuration committed successfully</line></details>
    </job>
  </result>
</response>
```

**Response (failed):**
```xml
<response status="success">
  <result>
    <job>
      <id>152</id>
      <status>FIN</status>
      <result>FAIL</result>
      <progress>100</progress>
      <details><line>Commit failed: validation error...</line></details>
    </job>
  </result>
</response>
```

### Job Status Values

| `<status>` | `<result>` | Meaning |
|---|---|---|
| `ACT` | `PEND` | Job is active, still running |
| `FIN` | `OK` | Completed successfully |
| `FIN` | `FAIL` | Completed with errors |

### Polling Strategy
1. Submit commit, extract job ID from response
2. Poll every 2-3 seconds with `show jobs id <job_id>`
3. Continue until `<status>` is `FIN`
4. Check `<result>` for `OK` or `FAIL`

---

## Naming Rules

### PAN-OS Object Naming Constraints

| Constraint | Value |
|---|---|
| Max length | 63 characters |
| Allowed characters | Alphanumeric, underscore `_`, hyphen `-`, period `.` |
| First character | Must be alphanumeric or underscore |
| Case sensitive | Yes |
| Reserved names | `any`, `application-default` (for services) |

### FortiGate → PAN-OS Name Sanitization
1. Replace disallowed characters with underscore `_`
2. Remove consecutive underscores
3. Ensure first character is alphanumeric or underscore
4. Truncate to 63 characters
5. Handle duplicates with `_2`, `_3` suffixes

### Comparison with FTD Naming

| Rule | FTD | PAN-OS |
|---|---|---|
| Max length | 48 chars | 63 chars |
| Hyphens | Not allowed | Allowed |
| Periods | Not allowed | Allowed |
| Case | Case-insensitive | Case-sensitive |

---

## PA-440 Hardware Reference

### Specifications
- **Form factor**: Desktop
- **Data ports**: 8x 1G copper (ethernet1/1 through ethernet1/8)
- **Management port**: 1x dedicated (mgmt)
- **Console**: 1x RJ-45
- **USB**: 1x USB-A
- **HA**: Supported (dedicated HA ports or use data ports)
- **PAN-OS support**: 10.1 and later

### Interface Naming
```
ethernet1/1  through  ethernet1/8    (data ports)
mgmt                                  (management - separate, not a data port)
loopback.X                            (loopback interfaces)
tunnel.X                              (tunnel interfaces)
```

### Default Virtual Router
- Name: `default`
- All interfaces assigned to `default` virtual router by default

### Default Zones
PAN-OS ships with no preconfigured zones. Zones must be created and interfaces assigned.

---

## Error Handling

### Response Format

**Success:**
```xml
<response status="success" code="20">
  <msg>command succeeded</msg>
</response>
```

**Error:**
```xml
<response status="error" code="12">
  <msg>
    <line>Object not found</line>
  </msg>
</response>
```

### Common Error Codes

| Code | Meaning |
|---|---|
| 1 | Unknown command |
| 2 | Internal error |
| 3 | Internal error |
| 5 | Unauthorized |
| 6 | Bad XPath |
| 7 | Object not present |
| 8 | Object not unique (ambiguous) |
| 10 | Reference count not zero (object in use) |
| 11 | Internal error |
| 12 | Invalid object (validation error) |
| 14 | Operation not possible |
| 18 | Invalid value |
| 22 | Session timed out |

### Handling Object-in-Use Errors (Code 10)
When deleting objects that are referenced by rules or groups, you must first remove the references. The error response will typically indicate which objects reference the one being deleted.

---

## Rate Limiting & Best Practices

### API Limits
- No official per-second rate limit published
- Practical limit: ~100-200 requests/second on PA-440
- Commit operations are serialized (one at a time)
- Long-running commits block subsequent commits

### Best Practices

1. **Batch with `set` actions**: Use `action=set` for idempotent object creation. Safe to re-run.
2. **Commit once at the end**: Do all configuration changes first, then commit once. Each commit takes 30-120 seconds.
3. **Check candidate config**: Use `action=get` to verify changes before committing.
4. **Handle 22 (session timeout)**: Re-generate API key and retry.
5. **Order of operations**:
   - Create address objects first
   - Create address groups (may reference addresses)
   - Create service objects
   - Create service groups (may reference services)
   - Create zones
   - Create static routes
   - Create security rules last (references all above)
6. **Deletion order**: Reverse of creation (rules first, then objects).
7. **Use `X-PAN-KEY` header**: Keeps API key out of URL/logs.
8. **SSL verification**: Self-signed certs are default; disable verification or add cert to trust store.

---

## Multi-Configuration Requests (PAN-OS 10.2+)

PAN-OS 10.2 and later support multiple configuration changes in a single API call using the `type=multi-config` request type.

```
POST https://<fw>/api/?type=multi-config&key=<key>
Content-Type: multipart/form-data

--boundary
Content-Disposition: form-data; name="action"
set
--boundary
Content-Disposition: form-data; name="xpath"
/config/devices/entry[@name='localhost.localdomain']/vsys/entry[@name='vsys1']/address
--boundary
Content-Disposition: form-data; name="element"
<entry name="host1"><ip-netmask>1.1.1.1/32</ip-netmask></entry>
<entry name="host2"><ip-netmask>2.2.2.2/32</ip-netmask></entry>
--boundary--
```

This can significantly reduce the number of API calls needed for bulk imports.

---

## Operational Commands

### Show System Info
```
GET https://<fw>/api/?type=op&cmd=<show><system><info></info></system></show>&key=<key>
```

### Show Routing Table
```
GET https://<fw>/api/?type=op&cmd=<show><routing><route></route></routing></show>&key=<key>
```

### Show Security Rules (hit count)
```
GET https://<fw>/api/?type=op&cmd=<show><rule-hit-count><vsys><vsys-name><entry name='vsys1'><rule-base><entry name='security'><rules><all/></rules></entry></rule-base></entry></vsys-name></vsys></rule-hit-count></show>&key=<key>
```

### Show Interfaces
```
GET https://<fw>/api/?type=op&cmd=<show><interface>all</interface></show>&key=<key>
```
