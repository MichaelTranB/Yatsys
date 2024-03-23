let divSelectRoom = document.getElementById('selectRoom');
let divConsultingRoom = document.getElementById('consultingRoom');
let inputRoomNumber = document.getElementById('roomNumber');
let btnGoRoom = document.getElementById('goRoom');
let localVideo = document.getElementById('localVideo');
let remoteVideo = document.getElementById('remoteVideo');
let btnJoinRoom = document.getElementById('joinRoom');
let roomNumber, localStream, remoteStream, rtcPeerConnection, isCaller, joined;

const iceServers = {
  iceServers: [
    { urls: 'stun:stun.services.mozilla.com' },
    { urls: 'stun:stun.l.google.com:19302' },
    {
        urls: "stun:a.relay.metered.ca:80",
      },
      {
        urls: "turn:a.relay.metered.ca:80",
        username: "placeholder_username",
        credential: "placeholder_value",
      },
      {
        urls: "turn:a.relay.metered.ca:80?transport=tcp",
        username: "placeholder_username",
        credential: "placeholder_value",
      },
      {
        urls: "turn:a.relay.metered.ca:443",
        username: "placeholder_username",
        credential: "placeholder_value",
      },
      {
        urls: "turn:a.relay.metered.ca:443?transport=tcp",
        username: "placeholder_username",
        credential: "placeholder_value",
      },
  ],
};

const streamConstraints = { audio: true, video: true };
console.log("Start initialization socketIO..")
const socket = io();
console.log("this is socketIO object",socket)
socket.on('connect', () => {
  console.log('Connected to the server');

  btnGoRoom.onclick = () => {
    let invalidRoomNumber = () => {
      alert('Please type a room name');
    };
    let validRoomNumber = () => {
      roomNumber = inputRoomNumber.value;
      socket.emit('create', roomNumber);
      divSelectRoom.style = 'display:none';
      divConsultingRoom.style = 'display:block';
    };
    inputRoomNumber.value === '' ? invalidRoomNumber() : validRoomNumber();
  };

  btnJoinRoom.onclick = () => {
    let invalidRoomNumber = () => {
      alert('Please type a room name');
    };
    let validRoomNumber = () => {
      roomNumber = inputRoomNumber.value;
      socket.emit('join', roomNumber);
      divSelectRoom.style = 'display:none';
      divConsultingRoom.style = 'display:block';
    };
    inputRoomNumber.value === '' ? invalidRoomNumber() : validRoomNumber();
  };

  socket.on('created', room => {
    navigator.mediaDevices
      .getUserMedia(streamConstraints)
      .then(stream => {
        localStream = stream;
        localVideo.srcObject = stream;
        isCaller = true;
        // socket.emit('ready', roomNumber);
        console.log("create room")
      })
      .catch(err => {
        console.log('An error occurred: ', err);
      });
  });

  socket.on('joined', room => {
    if (!isCaller && !joined) {
    console.log("you join the room")
      joined = true;
      socket.emit('ready', room);
    }
  });

  let onIceCandidate = event => {
    if (event.candidate) {
    console.log(`sending ice candidate: `, event.candidate);
      socket.emit('candidate', {
        type: 'candidate',
        label: event.candidate.sdpMLineIndex,
        id: event.candidate.sdpMid,
        candidate: event.candidate.candidate,
        room: roomNumber,
      });
    }
  };

  let onAddStream = event => {
    console.log(`start loading remote VideoStreaming...`);
    remoteVideo.srcObject = event.streams[0];
    remoteStream = event.streams[0];
  };

  socket.on('ready', async () => {
    if (isCaller) {
      console.log(`ready to create RTCPeerConnection for caller `);
      rtcPeerConnection = new RTCPeerConnection(iceServers);
      rtcPeerConnection.onicecandidate = onIceCandidate;
    //   rtcPeerConnection.ontrack = onAddStream;
      localStream.getTracks().forEach(track => {
        console.log(`add Track in rtcPeerConnection,`,track);
        rtcPeerConnection.addTrack(track, localStream);
      });

      const sessionDescription = await rtcPeerConnection.createOffer();
      await rtcPeerConnection.setLocalDescription(sessionDescription);
      console.log(`sending offer:`, sessionDescription);
      socket.emit('offer', {
        type: 'offer',
        sdp: rtcPeerConnection.localDescription,
        room: roomNumber,
      });
    }
  });

  socket.on('offer', async event => {
    if (!isCaller && !rtcPeerConnection) {
      rtcPeerConnection = new RTCPeerConnection(iceServers);
      rtcPeerConnection.onicecandidate = onIceCandidate;
      rtcPeerConnection.ontrack = onAddStream;
      console.log(`received offer:`, event)
      rtcPeerConnection.setRemoteDescription(new RTCSessionDescription(event));
      const sessionDescription = await rtcPeerConnection.createAnswer();
      await rtcPeerConnection.setLocalDescription(sessionDescription);
      console.log(`sending answer: `, sessionDescription)
      socket.emit('answer', {
        type: 'answer',
        sdp: sessionDescription,
        room: roomNumber,
      });
    }
  });

  socket.on('answer', async event => {
    console.log(`received answer: `, event)
    await rtcPeerConnection.setRemoteDescription(
      new RTCSessionDescription(event)
    );
  });

  socket.on('candidate', async event => {
    const candidate = new RTCIceCandidate({
      sdpMLineIndex: event.label,
      candidate: event.candidate,
    });
    console.log(`received candidate`, candidate);
    await rtcPeerConnection.addIceCandidate(candidate);
  });
});